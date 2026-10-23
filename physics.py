"""Local, reviewable PDF extraction and IB Physics metadata suggestions."""
import re
import math
from io import BytesIO

import fitz
from PIL import Image
from ocr import read_pages, region_text

TOPICS = {
    'A.1': 'Kinematics', 'A.2': 'Forces and momentum', 'A.3': 'Work, energy and power',
    'A.4': 'Rigid body mechanics', 'A.5': 'Galilean and special relativity',
    'B.1': 'Thermal energy transfers', 'B.2': 'Greenhouse effect', 'B.3': 'Gas laws',
    'B.4': 'Thermodynamics', 'B.5': 'Current and circuits',
    'C.1': 'Simple harmonic motion', 'C.2': 'Wave model', 'C.3': 'Wave phenomena',
    'C.4': 'Standing waves and resonance', 'C.5': 'Doppler effect',
    'D.1': 'Gravitational fields', 'D.2': 'Electric and magnetic fields',
    'D.3': 'Motion in electromagnetic fields', 'D.4': 'Induction',
    'E.1': 'Structure of the atom', 'E.2': 'Quantum physics', 'E.3': 'Radioactive decay',
    'E.4': 'Fission', 'E.5': 'Fusion and stars',
}
KEYWORDS = {
    'A.1': ['velocity', 'displacement', 'acceleration', 'projectile'],
    'A.2': ['momentum', 'newton', 'friction', 'impulse'],
    'A.3': ['kinetic energy', 'power', 'efficiency', 'work done'],
    'A.4': ['torque', 'moment of inertia', 'angular momentum'],
    'A.5': ['relativity', 'lorentz', 'time dilation'],
    'B.1': ['specific heat', 'thermal', 'latent heat'], 'B.2': ['greenhouse', 'albedo'],
    'B.3': ['ideal gas', 'gas pressure', 'molar'], 'B.4': ['entropy', 'thermodynamic'],
    'B.5': ['circuit', 'resistor', 'resistance', 'current'],
    'C.1': ['simple harmonic', 'oscillation', 'pendulum'],
    'C.2': ['wavelength', 'frequency', 'wave speed'],
    'C.3': ['diffraction', 'interference', 'refraction'],
    'C.4': ['standing wave', 'resonance', 'harmonic'], 'C.5': ['doppler'],
    'D.1': ['gravitational', 'orbit', 'escape speed'],
    'D.2': ['electric field', 'magnetic field', 'coulomb'],
    'D.3': ['charged particle', 'magnetic force', 'lorentz force'],
    'D.4': ['induction', 'magnetic flux', 'faraday', 'lenz'],
    'E.1': ['atomic', 'energy level', 'spectrum'],
    'E.2': ['photoelectric', 'de broglie', 'photon'],
    'E.3': ['half-life', 'radioactive', 'decay'], 'E.4': ['fission', 'chain reaction'],
    'E.5': ['fusion', 'star', 'luminosity'],
}
COMMANDS = ['calculate', 'define', 'describe', 'determine', 'discuss', 'draw', 'estimate',
            'evaluate', 'explain', 'identify', 'justify', 'outline', 'predict', 'show',
            'sketch', 'state', 'suggest', 'compare', 'deduce', 'distinguish']

PATTERNS = {
    'A.2': r'\b(force|collision|collides|collide|tension|weight|drag|buoyancy|upthrust)\b',
    'A.4': r'\b(angular (?:velocity|acceleration|momentum)|rotational|flywheel|rotates|rotating|rolls without slipping)\b',
    'A.5': r'\b(relativistic|space.time|proper time|proper lifetime|length contraction|inertial reference)\b',
    'B.1': r'\b(heat capacity|phase change|intermolecular|black.body|emissivity|thermal conductivit\w*)\b',
    'B.2': r'\b(energy balance|planet.s climate|solar radiation|greenhouse)\b',
    'B.3': r'\b((?:ideal |monatomic |diatomic )+gas|gas molecules|molecules of (?:an? )?ideal)\b',
    'B.4': r'\b(carnot|heat engine|isothermal|isobaric|adiabatic|microstates)\b',
    'C.2': r'\b(wavefronts?|electromagnetic wave|transverse wave|longitudinal wave)\b',
    'C.3': r'\b(refractive index|critical angle|double.slit|single.slit|diffracted|refracted)\b',
    'C.5': r'\b(red.shift|redshift|blue.shift|blueshift|doppler)\b',
    'D.1': r'\b(kepler|satellite|gravitational)\b',
    'D.2': r'\b(electric force|point charges?|equipotential|charged (?:rod|plate)|charged parallel plates)\b',
    'D.4': r'\b(induced|induction|magnetic flux|lenz|faraday)\b',
    'E.1': r'\b(bohr|rutherford|energy levels?|hydrogen atom|emission spectra|absorption spectra)\b',
    'E.2': r'\b(compton|photoelectrons?|photoelectric|de broglie)\b',
    'E.3': r'\b(binding energy|mass defect|beta.plus|alpha decay|beta decay)\b',
    'E.4': r'\b(moderator|moderators|nuclear power station|fission)\b',
}


def suggest(text, paper=None):
    lower = re.sub(r'\s+', ' ', text.lower().replace('−', '-').replace('–', '-'))
    totals = re.findall(r'total[^\n\d]{0,25}(\d+)\s*marks?', lower)
    marks = int(totals[-1]) if totals else sum(map(int, re.findall(r'\[(\d{1,2})\]', text)))
    marks = 1 if paper == 'Paper 1A' else (marks or None)
    evidence = {code: [w for w in words if re.search(r'\b' + re.escape(w) + r'(?:s)?\b', lower)]
                for code, words in KEYWORDS.items()}
    for code, pattern in PATTERNS.items():
        found = re.search(pattern, lower)
        if found:
            evidence[code].append(found[0])
    # OCR often joins an article to the next word, e.g. "Adiffraction".
    for word, code in [('diffraction', 'C.3'), ('force', 'A.2'), ('ball', 'A.2'), ('cylinder', 'A.4')]:
        if re.search(r'\ba' + word + r'\b', lower):
            evidence[code].append(word + ' (OCR joined article)')
    def add(code, label):
        evidence[code].append(label)
    if re.search(r'\b(?:a)?planet\b', lower) and 'free fall' in lower:
        add('D.1', 'planetary surface gravity')
    if re.search(r'\b(wave|waves)\b', lower) and not evidence['E.2']:
        add('C.2', 'wave model')
    if 'in phase' in lower and ('loudspeaker' in lower or 'minimum intensity' in lower):
        add('C.3', 'superposition of coherent sources')
    if 'driven' in lower and ('oscill' in lower or 'natural frequency' in lower):
        add('C.4', 'driven oscillation and resonance')
    if 'gas' in lower and 'work' in lower and 'internal energy' in lower:
        add('B.4', 'first law: gas heat and work')
    if re.search(r'\b(metal surface|metal surfaces)\b', lower) and 'electrons' in lower and re.search(r'\b(emitted|emit)\b', lower):
        add('E.2', 'electron emission from metal')
    if 'spaceship' in lower and re.search(r'0[.,][0-9]+\s*c\b', lower):
        add('A.5', 'relativistic spaceship speed')
    if 'current' in lower and 'wires' in lower and 'force' in lower:
        add('D.3', 'magnetic forces between current-carrying wires')
    if evidence['D.1'] and 'gravitational potential energy' in lower and not re.search(r'\b(planet|orbit|satellite|escape|field)\b', lower):
        evidence['D.1'] = []
        add('A.3', 'gravitational potential energy near Earth')
    if 'latent heat of fusion' in lower and not re.search(r'\b(nuclear|stars?|nuclei|stellar)\b', lower):
        evidence['E.5'] = []
    if evidence['E.1'] == ['atomic']:
        evidence['E.1'] = []
    if evidence['E.2'] == ['photon'] and (evidence['E.1'] or evidence['A.5']):
        evidence['E.2'] = []
    if 'conducting rod' in lower and 'rails' in lower and 'magnetic field' in lower:
        add('D.3', 'force on conducting rod in magnetic field')
        add('D.4', 'motional emf and magnetic braking')
    if 'in phase' in lower and ('waves' in lower or 'wavefronts' in lower):
        add('C.3', 'coherent-wave superposition')
    if 'closest approach' in lower and 'nucleus' in lower:
        add('D.2', 'electrostatic closest approach')
    if evidence['B.2'] and not re.search(r'\b(greenhouse|albedo|climate|atmosphere|atmospheric)\b', lower):
        evidence['B.2'] = []
    if 'no atmosphere' in lower and not re.search(r'\b(greenhouse|albedo|climate|solar radiation)\b', lower):
        evidence['B.2'] = []
    if re.search(r'\b(source|train|galaxy)\b', lower) and re.search(r'\b(moving|moves|approach\w*|shift\w*)\b', lower) and re.search(r'\b(wavelength|sound|spectr\w*|observer)\b', lower):
        add('C.5', 'moving source / observed waves')
    if re.search(r'(?:atmosphere.{0,300}(?:radiat|intensit)|(?:radiat|intensit).{0,300}atmosphere)', lower):
        add('B.2', 'atmospheric radiation balance')
    if re.search(r'\b(induced|induction)\b', lower) and 'magnetic' in lower:
        add('D.4', 'electromagnetic induction')
    if re.search(r'\b(electron|proton|charged particle)\b', lower) and re.search(r'\b(field|parallel plates)\b', lower) and re.search(r'\b(mov\w*|motion|path|speed|velocity|enter\w*)\b', lower):
        add('D.3', 'charged-particle motion in fields')
    if 'uranium' in lower and 'neutron' in lower and ('xenon' in lower or 'strontium' in lower):
        add('E.4', 'neutron-induced nuclear splitting')
    # These unqualified words are common outside their syllabus topics.
    if set(evidence['B.5']).issubset({'current', 'resistance'}) and not re.search(r'\b(electric\w*|charge|ampere|potential difference|voltage|ohm|thermistor|metal wire)\b', lower):
        evidence['B.5'] = []
    if evidence['C.2'] and not re.search(r'\b(wave|waves|sound|water|vibrat\w*|oscillat\w*|propagat\w*|refract\w*|diffract\w*|interferen\w*|doppler)\b', lower):
        evidence['C.2'] = []
    if evidence['A.3'] == ['power'] and re.search(r'\b(thermal|radiation|radiated|luminosity|black.body|solar|resistor|circuit)\b', lower):
        evidence['A.3'] = []
    # Prefer the specific syllabus topic when generic mechanics words are incidental.
    if paper == 'Paper 1A':
        if evidence['A.4']:
            evidence['A.1'] = evidence['A.2'] = evidence['A.3'] = []
        if evidence['A.5']:
            evidence['A.1'] = evidence['E.5'] = []
        if evidence['B.1'] or evidence['B.3'] or evidence['B.4']:
            evidence['A.3'] = []
        if evidence['B.3'] or evidence['B.4']:
            evidence['B.1'] = []
        if evidence['B.4']:
            evidence['B.3'] = []
        if evidence['C.1']:
            evidence['A.1'] = evidence['A.2'] = []
            if not re.search(r'\b(standing|resonance|harmonics|second harmonic|first harmonic|driven)\b', lower):
                evidence['C.4'] = []
        if evidence['C.5']:
            evidence['A.1'] = evidence['C.2'] = evidence['E.1'] = []
        if evidence['C.2']:
            evidence['A.1'] = []
        if evidence['C.4'] and 'driven' in lower:
            evidence['A.2'] = evidence['C.1'] = evidence['C.2'] = []
        if evidence['B.2']:
            evidence['B.3'] = []
        if evidence['B.5']:
            evidence['A.3'] = []
        if evidence['D.1']:
            evidence['A.1'] = evidence['A.2'] = evidence['A.3'] = []
            if not re.search(r'\b(electric|magnetic|charge\w*)\b', lower):
                evidence['D.2'] = []
        if evidence['D.2'] and ('electric force' in lower or 'magnetic force' in lower):
            evidence['A.2'] = []
        if evidence['D.3'] or evidence['D.4']:
            evidence['A.1'] = evidence['A.2'] = evidence['A.4'] = evidence['D.2'] = []
        if evidence['D.4']:
            evidence['D.3'] = []
        if evidence['D.2'] and 'electric' in lower and 'electron' in lower and 'paths' in lower:
            add('D.3', 'electron paths in an electric field')
            evidence['D.2'] = []
        if evidence['E.1']:
            evidence['D.1'] = evidence['D.3'] = []
        if evidence['E.2']:
            evidence['A.1'] = evidence['A.2'] = evidence['A.3'] = evidence['C.2'] = []
        if evidence['E.3']:
            evidence['A.2'] = []
        if evidence['E.4']:
            evidence['A.3'] = evidence['E.3'] = []
        if evidence['E.5']:
            evidence['E.1'] = []
    commands = [term for term in COMMANDS if re.search(r'\b' + term + r'\b', lower)]
    if 'state' in commands and not re.search(r'(?im)(?:^|[.!?]\s*|\)\s*)state\b', text):
        commands.remove('state')
    if paper == 'Paper 1A':
        commands = []  # MCQ prose and options are not imperative command-term prompts.
    return dict(topics=[code for code, matches in evidence.items() if matches],
                topic_evidence={code: matches for code, matches in evidence.items() if matches},
                commands=commands,
                marks=marks, minutes=round(marks * 1.8, 1) if marks else 5.0,
                difficulty='Unrated')


def document_metadata(text, filename):
    source = filename + '\n' + text[:6000]
    years = re.findall(r'\b(20\d{2})\b', source)
    year = int(years[0]) if years else None
    level = 'HL' if re.search(r'\b(HL|higher level)\b', source, re.I) else 'SL' if re.search(r'\b(SL|standard level)\b', source, re.I) else 'Unknown'
    paper = re.search(r'paper[\s_-]*([12])\s*([ab])?', source, re.I)
    return dict(year=year, level=level, paper=('Paper ' + paper[1] + (paper[2] or '').upper()) if paper else 'Unknown',
                syllabus='2025' if year and year >= 2025 else 'Legacy' if year else 'Unknown')


def extract(path, filename, ocr_mode='auto', page_records=None, ocr_cache=None):
    with fitz.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError('Password-protected PDFs are not supported. Upload an unlocked copy.')
        if len(pdf) > 150:
            raise ValueError('Upload a paper with at most 150 pages.')
        if not len(pdf):
            raise ValueError('PDF contains no pages.')
        records, ocr_warnings = read_pages(pdf, ocr_mode, ocr_cache) if page_records is None else (page_records, [])
        text = '\n'.join(r['native'] if len(r['native'].strip()) >= 50 else r['text'] for r in records)
        metadata = document_metadata(text, filename)
        labels, starts, numbering_warnings = [], [], []
        for index, record in enumerate(records):
            page = pdf[index]
            selected_lines = record['native_lines'] if len(record['native'].strip()) >= 50 else record['lines']
            for line in sorted(selected_lines, key=lambda l: (round(l['bbox'][1] / 3), l['bbox'][0])):
                match = re.match(r'^(\d{1,2})[.)](?:\s|$)', line['text'].strip())
                if (match and page.rect.width * .05 <= line['bbox'][0] <= page.rect.width * .20
                        and 50 < line['bbox'][1] < page.rect.height - 45):
                    labels.append((index, max(40, line['bbox'][1] - 5), int(match[1]), len(record['native'].strip()) < 50))
        expected = 1
        for i, (page_no, top, detected, is_ocr) in enumerate(labels):
            following = labels[i + 1][2] if i + 1 < len(labels) else None
            inferred = (is_ocr and detected != expected and str(detected).replace('4', '1') == str(expected)
                        and following == expected + 1)
            if detected == expected or inferred:
                if inferred:
                    numbering_warnings.append(f'Page {page_no + 1}: OCR read question {detected}; proposed {expected} from adjacent numbering. Confirm the image.')
                starts.append((page_no, top, expected))
                expected += 1
        candidates = []
        for i, (page_no, top, number) in enumerate(starts):
            end_page, end_y, _ = starts[i + 1] if i + 1 < len(starts) else (len(pdf) - 1, pdf[-1].rect.height - 30, 0)
            regions = []
            for n in range(page_no, end_page + 1):
                page = pdf[n]
                page_body = records[n]['native'] or records[n]['text']
                if re.search(r'(?im)^\s*(Disclaimer:|References:|Please do not write on this page)', page_body):
                    continue
                bottom = end_y if n == end_page else page.rect.height - 45
                y = top if n == page_no else 50
                if bottom <= y:
                    continue
                rect = [30, y, page.rect.width - 30, bottom]
                regions.append(dict(page=n, rect=rect))
            body = region_text(records, regions)
            ocr_text = region_text(records, regions, 'ocr')
            suggestions = suggest(body, metadata['paper'])
            ocr_suggestions = suggest(ocr_text, metadata['paper']) if ocr_text.strip() else None
            sources = ['native' if len(records[r['page']]['native'].strip()) >= 50 else 'ocr' for r in regions]
            comparison = dict(status='not_run', topics=[], commands=[])
            if ocr_suggestions:
                comparison = dict(status='agreement' if set(suggestions['topics']) == set(ocr_suggestions['topics']) else 'disagreement',
                                  topics=ocr_suggestions['topics'], commands=ocr_suggestions['commands'])
                if all(source == 'ocr' for source in sources):
                    comparison['status'] = 'ocr_only'
            candidates.append(dict(number=number, regions=regions, text=body, text_source='mixed' if len(set(sources)) > 1 else sources[0],
                                   ocr_comparison=comparison, **metadata, **suggestions))
        pages = [dict(width=round(p.rect.width, 2), height=round(p.rect.height, 2)) for p in pdf]
        warnings = ['Automatic crops and tags are suggestions. Review diagrams, continuations and boundaries before saving.', *ocr_warnings, *numbering_warnings]
        if len(text.strip()) < 50:
            warnings.append('No readable text found after extraction/OCR; create crops and enter metadata manually.')
        if not starts:
            warnings.append('No sequential question numbers detected. Add questions manually using page crops.')
        maximum = re.search(r'maximum mark.{0,100}?[\[(]?(\d{2,3})\s*marks?', re.sub(r'\s+', ' ', text[:10000]), re.I)
        expected_marks = int(maximum[1]) if maximum else None
        detected_marks = sum(q['marks'] or 0 for q in candidates)
        mark_audit = dict(expected=expected_marks, detected=detected_marks,
                          status='matched' if expected_marks == detected_marks else 'mismatch' if expected_marks else 'unknown')
        if mark_audit['status'] == 'mismatch':
            warnings.append(f'Detected {detected_marks} marks, but the cover states {expected_marks}. Review question marks and timing; OCR may omit mark brackets.')
        return dict(metadata=metadata, pages=pages, questions=candidates, warnings=warnings, text_pages=records,
                    mark_audit=mark_audit, ocr_pages=sum(bool(r.get('ocr_ran') or r['lines']) for r in records))


def validate_regions(pdf, regions):
    if not isinstance(regions, list) or not 1 <= len(regions) <= 30:
        raise ValueError('Each question needs between 1 and 30 page crops.')
    clean = []
    for region in regions:
        n = region['page']
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n < len(pdf):
            raise ValueError('Invalid page number.')
        rect = fitz.Rect([float(v) for v in region['rect']])
        if (not rect.is_valid or rect.is_empty or not pdf[n].rect.contains(rect)
                or rect.width < 5 or rect.height < 5):
            raise ValueError('Crop must be inside the page and at least 5 points wide and high.')
        clean.append(dict(page=n, rect=list(rect)))
    return clean


def render_question(pdf, regions):
    images = []
    width, padding = 1400, 60
    for region in regions:
        rect = fitz.Rect(region['rect'])
        pix = pdf[region['page']].get_pixmap(matrix=fitz.Matrix(min(3, (width - 2 * padding) / rect.width), min(3, (width - 2 * padding) / rect.width)), clip=rect, alpha=False)
        image = Image.open(BytesIO(pix.tobytes('png'))).convert('RGB')
        # Fixed output width and padding; never stretch a narrow crop above 3x.
        images.append(image)
    height = 2 * padding + sum(im.height for im in images) + 24 * (len(images) - 1)
    if height > 40000:
        raise ValueError('Question image is too tall. Use fewer or smaller crops.')
    canvas = Image.new('RGB', (width, height), 'white')
    y = padding
    for im in images:
        canvas.paste(im, ((width - im.width) // 2, y))
        y += im.height + 24
    output = BytesIO()
    canvas.save(output, format='PNG')
    return output.getvalue()


def choose_questions(questions, target):
    """Subset sum at tenth-minute resolution; each parent question is indivisible."""
    limit = math.floor(target * 10 + 1e-8)
    states = {0: ()}
    for q in questions:
        weight = max(1, math.ceil(q['minutes'] * 10 - 1e-8))
        for duration, chosen in list(states.items()):
            new = duration + weight
            if new <= limit and new not in states:
                states[new] = chosen + (q['id'],)
    return states[max(states)]
