from pathlib import Path

import pytest

from app.contracts import UploadRequest
from app.errors import ContentInvalid
from app.services.youtube.validators import (
    create_upload_request, validate_description, validate_tags, validate_title, validate_upload_request,
)


def test_validator_boundaries():
    validate_title('a' * 100)
    validate_description('ế' * 1666 + 'aa')  # Exactly 5000 UTF-8 bytes.
    validate_tags(['a' * 500])
    for function, value in [(validate_title, 'a' * 101), (validate_title, ''),
        (validate_description, 'ế' * 1667), (validate_tags, ['a' * 501]),
        (validate_tags, ['a' * 250, 'b' * 250]),  # Separating comma counts.
        (validate_tags, ['a b' + 'x' * 496])]:  # Spaces require two quote characters.
        with pytest.raises(ContentInvalid):
            function(value)


@pytest.mark.parametrize('function,value', [(validate_title, '<title>'), (validate_description, 'bad >'),
    (validate_tags, ['<tag']), (validate_tags, 'abc'), (validate_title, None)])
def test_invalid_values(function, value):
    with pytest.raises(ContentInvalid):
        function(value)


def test_audience_required_in_factory_and_rights_checked():
    with pytest.raises(TypeError):
        create_upload_request(path=Path('demo.mp4'), title='Title', description='', tags=[])
    req = create_upload_request(path=Path('demo.mp4'), title='Title', description='', tags=[], made_for_kids=False)
    assert isinstance(req, UploadRequest) and req.privacy == 'private'
    with pytest.raises(ContentInvalid):
        validate_upload_request(req)
    req.rights_confirmed = True
    validate_upload_request(req)
    req.made_for_kids = None
    with pytest.raises(ContentInvalid):
        validate_upload_request(req)
