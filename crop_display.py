"""Display-only crop tightening; saved geometry and OCR remain unchanged."""
import fitz


def display_regions(regions, paper='Unknown', parent_regions=None):
    if paper not in ('Paper 1', 'Paper 1A', 'Paper 1B'):
        return regions
    # Trim the parent's bottom edge, never each internal subquestion boundary.
    # This also keeps Short/topic-filtered views aligned with the full question.
    result = []
    for region in regions:
        area = fitz.Rect(region['rect'])
        for parent in ([region] if parent_regions is None else parent_regions):
            if parent['page'] != region['page']:
                continue
            bounds = fitz.Rect(parent['rect'])
            bounds.y1 -= bounds.height * .05
            clipped = area & bounds
            if not clipped.is_empty:
                result.append(dict(region, rect=list(clipped)))
    return result
