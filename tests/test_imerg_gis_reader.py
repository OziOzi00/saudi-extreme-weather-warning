from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
from PIL import Image

from saudi_warning.verification.observations import read_imerg_gis_daily_zip


def test_read_imerg_daily_zip_scales_missing_and_coordinates(tmp_path) -> None:
    raw = np.array([[10, 29999], [0, 25]], dtype=np.uint16)
    image = Image.fromarray(raw)
    buffer = BytesIO()
    image.save(buffer, format="TIFF", compression="tiff_lzw")
    stem = "3B-DAY-GIS.MS.MRG.3IMERG.20200101-S000000-E235959.0000.V07B"
    archive_path = tmp_path / f"{stem}.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(f"{stem}.total.accum.tif", buffer.getvalue())
        archive.writestr(
            f"{stem}.total.accum.tfw",
            "0.1\n0\n0\n-0.1\n34.05\n33.95\n",
        )

    field = read_imerg_gis_daily_zip(archive_path)
    assert field.shape == (2, 2)
    assert field.attrs["units"] == "mm"
    assert field.latitude.values.tolist() == [33.95, 33.85]
    assert field.longitude.values.tolist() == [34.05, 34.15]
    assert float(field.values[0, 0]) == 1.0
    assert np.isnan(field.values[0, 1])
    assert float(field.values[1, 1]) == 2.5
