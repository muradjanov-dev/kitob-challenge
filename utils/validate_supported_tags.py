from bs4 import BeautifulSoup


def is_valid_content(html):
    """
    supported tags:
    <b> <strong> <i> <em> <s> <u> <pre>
    """
    soup = BeautifulSoup(html, 'html.parser')
    SUPPORTED_TAGS = ['b', 'strong', 'i', 'em', 's', 'u', 'pre', 'br', 'p']
    for tag in soup.find_all():
        if tag.name not in SUPPORTED_TAGS:
            return False
    return True


def validate_content(html):
    return html.replace('<p>', '').replace('</p>', '').replace('<br>', '\n').replace('&nbsp;', ' ').replace('<br />', '').replace('&#39;', "'")
