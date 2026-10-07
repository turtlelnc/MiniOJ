def compare(actual: bytes, expected: bytes, mode: str) -> bool:
    if mode == 'exact':
        return actual == expected
    if mode != 'trimmed':
        raise ValueError('Unknown checker')
    def normalize(data):
        return b'\n'.join(line.rstrip(b' \t') for line in data.split(b'\n')).rstrip(b'\n')
    return normalize(actual) == normalize(expected)
