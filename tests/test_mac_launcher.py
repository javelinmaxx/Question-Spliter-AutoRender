import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('ready,running',[(True,False),(False,False),(True,True)])
def test_one_click_launcher_starts_existing_install_or_bootstraps(tmp_path,ready,running):
    repo=tmp_path/'Project with spaces';(repo/'scripts').mkdir(parents=True)
    shutil.copyfile(ROOT/'Install and Start.command',repo/'Install and Start.command')
    (repo/'scripts'/'setup_macos.sh').write_text('#!/bin/bash\nprintf "setup:%s\\n" "$*" >> "$LAUNCH_LOG"\n')
    fakebin=tmp_path/'bin';fakebin.mkdir()
    uname=fakebin/'uname';uname.write_text('#!/bin/bash\necho Darwin\n');uname.chmod(0o755)
    (repo/'.venv'/'bin').mkdir(parents=True)
    python=repo/'.venv'/'bin'/'python'
    python.write_text('#!/bin/bash\nif [ "${2:-}" = --open-existing ]; then exit "$RUNNING_STATUS"; fi\nif [ "$1" = scripts/check_installation.py ]; then exit "$READY_STATUS"; fi\nprintf "start:%s\\n" "$*" >> "$LAUNCH_LOG"\n')
    python.chmod(0o755)
    log=tmp_path/'launch.log'
    env=dict(os.environ,PATH=str(fakebin)+':'+os.environ['PATH'],READY_STATUS='0' if ready else '1',RUNNING_STATUS='0' if running else '1',LAUNCH_LOG=str(log))
    result=subprocess.run(['/bin/bash',str(repo/'Install and Start.command')],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    assert (log.read_text() if log.exists() else '')==('' if running else 'start:app.py\n' if ready else 'setup:--bootstrap\n')


def test_installer_check_reports_missing_pins_without_installing(tmp_path,monkeypatch):
    import importlib.util
    spec=importlib.util.spec_from_file_location('check_installation',ROOT/'scripts'/'check_installation.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    (tmp_path/'requirements.txt').write_text('A-package-that-does-not-exist==1.0\n')
    assert any('A-package-that-does-not-exist' in issue and 'missing' in issue for issue in module.installation_issues(tmp_path))


def test_launcher_reopens_only_the_correct_running_bank(tmp_path,monkeypatch):
    import importlib.util
    from threading import Thread
    from werkzeug.serving import make_server
    from app import create_app
    spec=importlib.util.spec_from_file_location('check_installation',ROOT/'scripts'/'check_installation.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    data=tmp_path/'instance';server=make_server('127.0.0.1',0,create_app(data))
    worker=Thread(target=server.serve_forever,daemon=True);worker.start()
    opened=[]
    monkeypatch.setenv('PORT',str(server.server_port));monkeypatch.setenv('QUESTION_BANK_DATA',str(data))
    monkeypatch.setenv('QUESTION_BANK_OPEN_BROWSER','1')
    monkeypatch.setattr(module.webbrowser,'open',lambda url,**kwargs:opened.append(url) or True)
    try:
        assert module.open_existing_server(tmp_path)
        assert opened==[f'http://127.0.0.1:{server.server_port}']
        monkeypatch.setenv('QUESTION_BANK_DATA',str(tmp_path/'different-bank'))
        assert not module.open_existing_server(tmp_path) and len(opened)==1
    finally:
        server.shutdown();worker.join(5);server.server_close()
