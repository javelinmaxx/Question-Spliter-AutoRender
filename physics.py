"""Local, reviewable PDF extraction and IB Physics metadata suggestions."""
import re
import math
from io import BytesIO

import fitz
from PIL import Image

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


def suggest(text):
    lower = text.lower()
    totals = re.findall(r'total[^\n\d]{0,25}(\d+)\s*marks?', lower)
    marks = int(totals[-1]) if totals else sum(map(int, re.findall(r'\[(\d{1,2})\]', text)))
    marks = marks or None
    return dict(topics=[code for code, words in KEYWORDS.items() if any(w in lower for w in words)],
                commands=[term for term in COMMANDS if re.search(r'\b' + term + r'\b', lower)],
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


def extract(path, filename):
    with fitz.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError('Password-protected PDFs are not supported. Upload an unlocked copy.')
        if len(pdf) > 150:
            raise ValueError('Upload a paper with at most 150 pages.')
        if not len(pdf):
            raise ValueError('PDF contains no pages.')
        text = '\n'.join(page.get_text() for page in pdf)
        metadata = document_metadata(text, filename)
        starts = []
        expected = 1
        for index, page in enumerate(pdf):
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    value = ''.join(span['text'] for span in line['spans']).strip()
                    match = re.match(r'^(\d{1,2})(?:[.)]\s*|\s+)(?=[A-Za-z(])', value)
                    if not match:
                        match = re.fullmatch(r'(\d{1,2})[.)]?', value)
                    if (match and int(match[1]) == expected and line['bbox'][0] <= page.rect.width * .24
                            and 35 < line['bbox'][1] < page.rect.height - 35):
                        starts.append((index, max(30, line['bbox'][1] - 5), expected))
                        expected += 1
        candidates = []
        for i, (page_no, top, number) in enumerate(starts):
            end_page, end_y, _ = starts[i + 1] if i + 1 < len(starts) else (len(pdf) - 1, pdf[-1].rect.height - 30, 0)
            regions, parts = [], []
            for n in range(page_no, end_page + 1):
                page = pdf[n]
                bottom = end_y if n == end_page else page.rect.height - 30
                y = top if n == page_no else 35
                if bottom <= y:
                    continue
                rect = [30, y, page.rect.width - 30, bottom]
                regions.append(dict(page=n, rect=rect))
                parts.append(page.get_text(clip=fitz.Rect(rect)))
            body = '\n'.join(parts)
            candidates.append(dict(number=number, regions=regions, text=body, **metadata, **suggest(body)))
        pages = [dict(width=round(p.rect.width, 2), height=round(p.rect.height, 2)) for p in pdf]
        warnings = ['Automatic crops and tags are suggestions. Review diagrams, continuations and boundaries before saving.']
        if len(text.strip()) < 50:
            warnings.append('This PDF appears scanned. OCR is not included; create crops and enter metadata manually.')
        if not starts:
            warnings.append('No sequential question numbers detected. Add questions manually using page crops.')
        return dict(metadata=metadata, pages=pages, questions=candidates, warnings=warnings)


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
