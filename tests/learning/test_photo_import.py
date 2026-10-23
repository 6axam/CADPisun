from __future__ import annotations

import base64
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

pytest.importorskip("PySide6")

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage

from handwriting_plotter.adapters.images.qt import QtImageDecoder
from handwriting_plotter.domain.models import canonical_json_bytes
from handwriting_plotter.learning.models import (
    ConfidenceValue,
    ImageTransform,
    NotebookPhoto,
    PageDimensions,
    PhotoImportMetadata,
    PhotoRegion,
    PixelFrame,
    PixelPoint,
    RulingEstimate,
)
from handwriting_plotter.learning.repository import (
    MAX_PHOTO_MANIFEST_BYTES,
    PhotoImportLimits,
    PhotoRepository,
    load_photo_bytes,
    serialize_photo,
)


def image_bytes(format_name: str, *, width: int = 12, height: int = 8) -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0xFF3366AA)
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, format_name), f"Qt cannot encode {format_name}"
    buffer.close()
    return bytes(encoded)


def import_fixture(tmp_path: Path, *, format_name: str = "PNG"):
    content = image_bytes(format_name)
    suffix = ".jpg" if format_name == "JPEG" else f".{format_name.lower()}"
    source = tmp_path / f"нотатки{suffix}"
    source.write_bytes(content)
    repository = PhotoRepository(tmp_path / "photo-data")
    record = repository.import_file(
        source,
        QtImageDecoder(),
        imported_at_utc="2026-10-23T12:00:00Z",
        application_version="test",
        source_kind="camera_photo",
        rights_status="private_user_material",
        source_id="photo-fixture",
    )
    return repository, record, source, content


@pytest.mark.parametrize(
    ("format_name", "detected_format", "media_type"),
    [
        ("PNG", "png", "image/png"),
        ("JPEG", "jpeg", "image/jpeg"),
        ("WEBP", "webp", "image/webp"),
        ("BMP", "bmp", "image/bmp"),
    ],
)
def test_real_qt_formats_import_save_and_reopen_losslessly(
    tmp_path: Path, format_name: str, detected_format: str, media_type: str,
) -> None:
    repository, record, source, content = import_fixture(tmp_path, format_name=format_name)

    assert record.photo.original_sha256 == sha256(content).hexdigest()
    assert record.photo.metadata.original_filename == source.name
    assert record.photo.metadata.detected_format == detected_format
    assert record.photo.metadata.media_type == media_type
    assert record.photo.metadata.decoder_id == "qt-qimagereader"
    assert record.photo.page_dimensions.width_px == 12
    assert record.photo.page_dimensions.height_px == 8
    assert record.photo.page_dimensions.width_mm is None
    assert record.photo.ruling.status == "not_evaluated"
    assert repository.load(record.sha256) == record.photo
    assert repository.read_original(record.photo) == content
    assert repository.list_records() == (record,)
    assert record.path.is_relative_to((tmp_path / "photo-data").resolve())
    assert not list((tmp_path / "photo-data").rglob("*.tmp"))

    source.write_bytes(b"the source file changed after import")
    reopened = PhotoRepository(tmp_path / "photo-data").load(record.sha256)
    assert reopened == record.photo
    assert PhotoRepository(tmp_path / "photo-data").read_original(reopened) == content


def test_repeat_import_reuses_immutable_original_and_manifest(tmp_path: Path) -> None:
    repository, first, source, content = import_fixture(tmp_path)
    second = repository.import_file(
        source,
        QtImageDecoder(),
        imported_at_utc="2026-10-23T12:00:00Z",
        application_version="test",
        source_kind="camera_photo",
        rights_status="private_user_material",
        source_id="photo-fixture",
    )
    assert second == first
    originals = list((tmp_path / "photo-data" / "originals").rglob("*.bin"))
    manifests = list((tmp_path / "photo-data" / "manifests").rglob("*.hp-photo.json"))
    assert len(originals) == len(manifests) == 1
    assert originals[0].read_bytes() == content


def test_static_gif_is_imported_as_single_raster(tmp_path: Path) -> None:
    content = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
    source = tmp_path / "static.gif"
    source.write_bytes(content)
    record = PhotoRepository(tmp_path / "data").import_file(
        source, QtImageDecoder(), imported_at_utc="2026-10-23T12:00:00Z",
        application_version="test", source_id="static-gif",
    )
    assert record.photo.metadata.detected_format == "gif"
    assert record.photo.metadata.media_type == "image/gif"
    assert record.photo.page_dimensions.width_px == 1
    assert record.photo.page_dimensions.height_px == 1


def test_tiff_is_rejected_before_unstable_full_decode() -> None:
    content = image_bytes("TIFF")
    with pytest.raises(ValueError, match="UNSUPPORTED_PHOTO_FORMAT"):
        QtImageDecoder().probe(content, PhotoImportLimits())


def test_import_limits_reject_encoded_dimension_and_pixel_bombs(tmp_path: Path) -> None:
    source = tmp_path / "sample.png"
    source.write_bytes(image_bytes("PNG", width=12, height=8))

    with pytest.raises(ValueError, match="PHOTO_FILE_TOO_LARGE"):
        PhotoRepository(
            tmp_path / "encoded", limits=PhotoImportLimits(max_encoded_bytes=8),
        ).import_file(
            source, QtImageDecoder(), imported_at_utc="2026-10-23T12:00:00Z",
            application_version="test",
        )
    with pytest.raises(ValueError, match="PHOTO_DIMENSION_LIMIT_EXCEEDED"):
        PhotoRepository(
            tmp_path / "dimension", limits=PhotoImportLimits(max_dimension_px=10),
        ).import_file(
            source, QtImageDecoder(), imported_at_utc="2026-10-23T12:00:00Z",
            application_version="test",
        )
    with pytest.raises(ValueError, match="PHOTO_PIXEL_LIMIT_EXCEEDED"):
        PhotoRepository(
            tmp_path / "pixels", limits=PhotoImportLimits(max_decoded_pixels=95),
        ).import_file(
            source, QtImageDecoder(), imported_at_utc="2026-10-23T12:00:00Z",
            application_version="test",
        )
    assert not (tmp_path / "encoded").exists()
    assert not (tmp_path / "dimension").exists()
    assert not (tmp_path / "pixels").exists()


@pytest.mark.parametrize("content", [b"not an image", b"<svg/>", b"%PDF-1.7\n", b"II*\x00"])
def test_import_rejects_corrupt_and_non_raster_content(tmp_path: Path, content: bytes) -> None:
    source = tmp_path / "misleading.png"
    source.write_bytes(content)
    with pytest.raises(ValueError, match="UNSUPPORTED_PHOTO_FORMAT|INVALID_PHOTO_IMAGE"):
        PhotoRepository(tmp_path / "data").import_file(
            source, QtImageDecoder(), imported_at_utc="2026-10-23T12:00:00Z",
            application_version="test",
        )


def test_repository_detects_original_and_manifest_tampering(tmp_path: Path) -> None:
    repository, record, _source, content = import_fixture(tmp_path)
    original_path = repository.original_path(record.photo.original_sha256)
    original_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="PHOTO_ORIGINAL_HASH_MISMATCH"):
        repository.load(record.sha256)

    original_path.write_bytes(content)
    record.path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="PHOTO_MANIFEST_HASH_MISMATCH"):
        repository.load(record.sha256)


def test_manifest_round_trip_preserves_regions_transforms_and_confidence(tmp_path: Path) -> None:
    _repository, record, _source, _content = import_fixture(tmp_path)
    identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    source = record.photo
    data = source.model_dump(mode="python")
    data["frames"] = (
        source.frames[0],
        PixelFrame(frame_id="corrected-pixels", width_px=12, height_px=8),
    )
    data["transforms"] = (ImageTransform(
        transform_id="identity-1",
        kind="homography",
        algorithm_id="synthetic-test/1",
        input_sha256=source.original_sha256,
        output_sha256="f" * 64,
        input_frame_id="source-pixels",
        output_frame_id="corrected-pixels",
        forward_matrix=identity,
        inverse_matrix=identity,
        parameters={"fixture": True},
    ),)
    confidence = ConfidenceValue(value=0.75, origin="heuristic", meaning="synthetic fixture")
    data["regions"] = (
        PhotoRegion(
            region_id="line-1", kind="line", frame_id="corrected-pixels",
            polygon=(PixelPoint(x=0, y=0), PixelPoint(x=12, y=0),
                     PixelPoint(x=12, y=4), PixelPoint(x=0, y=4)),
            confidence=confidence,
        ),
        PhotoRegion(
            region_id="word-1", kind="word", frame_id="corrected-pixels", parent_id="line-1",
            polygon=(PixelPoint(x=1, y=1), PixelPoint(x=6, y=1),
                     PixelPoint(x=6, y=3), PixelPoint(x=1, y=3)),
        ),
    )
    data["ruling"] = RulingEstimate(
        frame_id="corrected-pixels", classification="squared", status="proposed",
        method="synthetic-test/1", confidence=confidence,
        cell_pitch_x_px=2.0, cell_pitch_y_px=2.0, origin_x_px=0.5, origin_y_px=0.5,
    )
    enriched = NotebookPhoto.model_validate(data, strict=True)
    encoded = serialize_photo(enriched)
    assert load_photo_bytes(encoded) == enriched
    assert json.loads(encoded)["regions"][1]["parent_id"] == "line-1"


def test_models_reject_unsafe_paths_invalid_geometry_and_unknown_schema(tmp_path: Path) -> None:
    _repository, record, _source, _content = import_fixture(tmp_path)
    data = record.photo.model_dump(mode="python")
    data["original_relative_path"] = "../outside.bin"
    with pytest.raises(ValidationError, match="PHOTO_PATH_MUST_BE_SAFE_RELATIVE"):
        NotebookPhoto.model_validate(data, strict=True)

    data = record.photo.model_dump(mode="python")
    data["regions"] = (PhotoRegion(
        region_id="outside", kind="line", frame_id="source-pixels",
        polygon=(PixelPoint(x=0, y=0), PixelPoint(x=13, y=0), PixelPoint(x=0, y=1)),
    ),)
    with pytest.raises(ValidationError, match="REGION_OUTSIDE_PIXEL_FRAME"):
        NotebookPhoto.model_validate(data, strict=True)

    decoded = json.loads(serialize_photo(record.photo))
    decoded["schema_version"] = "2.0"
    with pytest.raises(ValueError, match="UNSUPPORTED_PHOTO_SCHEMA"):
        load_photo_bytes(canonical_json_bytes(decoded))
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_photo_bytes(b'{"format":"hp-notebook-photo","format":"hp-notebook-photo"}')
    with pytest.raises(ValueError, match="PHOTO_MANIFEST_TOO_LARGE"):
        load_photo_bytes(b" " * (MAX_PHOTO_MANIFEST_BYTES + 1))


def test_model_invariants_reject_false_scale_confidence_and_geometry() -> None:
    with pytest.raises(ValidationError, match="KNOWN_SCALE_REQUIRES_MM_DIMENSIONS"):
        PageDimensions(width_px=10, height_px=20, physical_scale_source="user_entered")
    with pytest.raises(ValidationError, match="CALIBRATED_CONFIDENCE_REQUIRES_REFERENCE"):
        ConfidenceValue(value=0.9, origin="calibrated", meaning="test")
    with pytest.raises(ValidationError, match="AUTHORIZED_PHOTO_REQUIRES_CONSENT_REFERENCE"):
        PhotoImportMetadata(
            original_filename="page.png", imported_at_utc="2026-10-23T12:00:00Z",
            application_version="test", detected_format="png", media_type="image/png",
            encoded_bytes=10, decoder_id="test", decoder_version="1", rights_status="authorized",
        )
    with pytest.raises(ValidationError, match="REGION_POLYGON_HAS_NO_AREA"):
        PhotoRegion(
            region_id="flat", kind="line", frame_id="source-pixels",
            polygon=(PixelPoint(x=0, y=0), PixelPoint(x=1, y=1), PixelPoint(x=2, y=2)),
        )
    identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    wrong_inverse = (2.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    with pytest.raises(ValidationError, match="TRANSFORM_INVERSE_MISMATCH"):
        ImageTransform(
            transform_id="bad", kind="homography", algorithm_id="test/1",
            input_sha256="0" * 64, output_sha256="1" * 64,
            input_frame_id="source", output_frame_id="corrected",
            forward_matrix=identity, inverse_matrix=wrong_inverse,
        )
    with pytest.raises(ValidationError, match="TRANSFORM_PARAMETERS_MUST_BE_CANONICAL_JSON"):
        ImageTransform(
            transform_id="nan", kind="other", algorithm_id="test/1",
            input_sha256="0" * 64, output_sha256="1" * 64,
            input_frame_id="source", output_frame_id="corrected",
            forward_matrix=identity, inverse_matrix=identity, parameters={"value": float("nan")},
        )


def test_repository_rejects_noncanonical_stored_path(tmp_path: Path) -> None:
    repository, record, _source, content = import_fixture(tmp_path)
    data = record.photo.model_dump(mode="python")
    data["original_relative_path"] = "originals/00/" + "0" * 64 + ".bin"
    changed = NotebookPhoto.model_validate(data, strict=True)
    with pytest.raises(ValueError, match="PHOTO_ORIGINAL_PATH_MISMATCH"):
        repository.store(changed, content)


def test_repository_store_cannot_bypass_decoded_pixel_limits(tmp_path: Path) -> None:
    repository, record, _source, content = import_fixture(tmp_path)
    constrained = PhotoRepository(
        tmp_path / "constrained", limits=PhotoImportLimits(max_decoded_pixels=95),
    )
    with pytest.raises(ValueError, match="PHOTO_PIXEL_LIMIT_EXCEEDED"):
        constrained.store(record.photo, content)
    assert not (tmp_path / "constrained").exists()


def test_repository_rejects_symlink_escape_from_data_root(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    outside = tmp_path / "outside"
    data_root.mkdir()
    outside.mkdir()
    try:
        (data_root / "originals").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable for this test user")
    source = tmp_path / "sample.png"
    source.write_bytes(image_bytes("PNG"))
    with pytest.raises(ValueError, match="PHOTO_PATH_OUTSIDE_DATA_ROOT"):
        PhotoRepository(data_root).import_file(
            source, QtImageDecoder(), imported_at_utc="2026-10-23T12:00:00Z",
            application_version="test",
        )
    assert not list(outside.iterdir())


def test_learning_core_import_does_not_load_qt() -> None:
    script = (
        "import sys; import handwriting_plotter.learning; "
        "assert not any(name.startswith('PySide6') for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", script], check=True)
