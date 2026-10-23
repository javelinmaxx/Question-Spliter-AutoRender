"""Inclusive, optionally open-ended year ranges shared by search and generation."""
import re


def year_range(values):
    def parse(name):
        value=values.get(name)
        if value in (None, ''):
            return None
        if isinstance(value, bool) or not re.fullmatch(r'\d{4}', str(value)) or not 1970 <= int(value) <= 2100:
            raise ValueError('Years must be whole numbers between 1970 and 2100.')
        return int(value)
    lower, upper, exact = parse('year_min'), parse('year_max'), parse('year')
    if exact is not None:
        if lower is not None or upper is not None:
            raise ValueError('Use a year range or an exact year, not both.')
        lower = upper = exact
    if lower is not None and upper is not None and lower > upper:
        raise ValueError('From year must be earlier than or equal to To year.')
    return lower, upper


def matches_year(year, lower, upper):
    if lower is None and upper is None:
        return True
    if year is None:
        return False
    return (lower is None or year >= lower) and (upper is None or year <= upper)
