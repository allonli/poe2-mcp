import base64
import sys
import zlib
from pathlib import Path
 
import pytest
 
sys.path.insert(0, str(Path(__file__).parent.parent))
 
from src.pob.importer import PoBImporter
 
 
@pytest.mark.asyncio
async def test_import_pob_urlsafe_base64_with_missing_padding():
    importer = PoBImporter()
 
    urlsafe_code = None
    for i in range(1, 5000):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<PathOfBuilding2>"
            f'<Build name="test-{i}" level="1" className="Witch" ascendClassName="Blood Mage" />'
            "</PathOfBuilding2>"
        )
        compressed = zlib.compress(xml.encode("utf-8"))
        b64 = base64.b64encode(compressed).decode("ascii")
        if "+" in b64 or "/" in b64:
            urlsafe_code = b64.replace("+", "-").replace("/", "_").rstrip("=")
            break
 
    if urlsafe_code is None:
        pytest.skip("Could not generate a deterministic URL-safe Base64 sample")
 
    build = await importer.import_build(urlsafe_code)
    assert build["class"] == "Witch"
    assert build["ascendancy"] == "Blood Mage"
