"""Compact trusted curriculum guidance for the optional local model."""
import json
from pathlib import Path

POLICY = json.loads((Path(__file__).parent / 'curriculum_prerequisites.json').read_text())
OCR_PROMPT_VERSION = f"physics-ocr-v2-curriculum-{POLICY['version']}"
DEPENDENCY_PROMPT_VERSION = f"physics-dependencies-v2-curriculum-{POLICY['version']}"

# Contrast the concepts most likely to be confused by keyword/OCR tagging.
BOUNDARIES = [
    ({'A.0'}, 'A.0 is the application skills category, not an official IB 2025 subtopic. Tag it for assessed uncertainty, errors, units, measurement or instrument skills, not incidental numerical measurements.'),
    ({'A.1', 'A.2', 'A.3', 'D.1'}, 'A.1 describes motion; A.2 explains it with forces/momentum and includes centripetal force. D.1 needs gravitational fields, potential or orbital gravity. A.3 needs assessed work, energy or power; motion alone is insufficient. Example: tension in a string driving circular motion is A.2, NOT D.1. A satellite orbit governed by gravity can assess D.1 and A.2.'),
    ({'A.2', 'A.4'}, 'Circular motion of a point mass is A.2. Torque, rotational inertia and angular momentum of extended rigid bodies are A.4.'),
    ({'B.1', 'B.2', 'B.3', 'B.4'}, 'B.1: heat transfer/storage. B.2: planetary radiation balance/greenhouse effect. B.3: gas state laws/kinetic model. B.4: first/second law, thermodynamic processes and engines.'),
    ({'B.5', 'D.2', 'D.3', 'D.4'}, 'B.5: circuit current, voltage and resistance. D.2: electric/magnetic field properties and potentials. D.3: forces/trajectories of moving charges or currents in fields. D.4: changing magnetic flux and induced emf.'),
    ({'C.1', 'C.2', 'C.3', 'C.4', 'C.5'}, 'C.1: oscillating systems. C.2: propagation, wave quantities and wave speed. C.3: refraction/diffraction/interference. C.4: standing modes/resonance. C.5: frequency/wavelength change from relative source-observer motion; frequency alone is insufficient. Example: explain redshift of a receding source -> C.5 only; calculate wave speed from frequency and wavelength -> C.2.'),
    ({'E.1', 'E.2', 'E.3', 'E.4', 'E.5'}, 'E.1: atomic/nuclear structure, discrete energy levels and spectra. E.2: photoelectric effect, matter waves and quantum behaviour. E.3: radioactive decay/activity. E.4: fission/chains. E.5: fusion/stars. A photon or nucleus mentioned alone does not establish all these topics.'),
]


def curriculum_context(codes):
    """Retrieve relevant summaries, keeping the full exam text within context."""
    selected = sorted(set(codes) & POLICY['topic_analysis'].keys())
    return dict(
        course='IB DP Physics, first assessment 2025; legacy questions map to this application catalogue, not their old numeric topic codes.',
        authority='Summaries from the repository teacher-support-material analysis. Prerequisites are application deductions, not an official IB teaching order.',
        level_note='HL-only categories: A.4, A.5, B.4, D.4, E.2. Shared categories may contain additional HL material; a topic name alone does not establish SL suitability.',
        topic_guidance={code: dict(assesses=POLICY['topic_analysis'][code]['summary'],
                                  earlier_foundations=POLICY['requires'][code]) for code in selected},
        distinctions=[text for group, text in BOUNDARIES if group.intersection(selected)],
    )
