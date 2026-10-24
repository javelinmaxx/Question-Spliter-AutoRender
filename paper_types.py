"""Source paper identity and asymmetric structured-paper filtering."""
PAPERS = ('Paper 1', 'Paper 1A', 'Paper 1B', 'Paper 2', 'Paper 3')


def matches_paper(actual, requested):
    return not requested or actual == requested or requested == 'Paper 2' and actual == 'Paper 3'
