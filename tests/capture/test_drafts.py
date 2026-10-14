from __future__ import annotations

from handwriting_plotter.capture.drafts import DraftCatalog, DraftEvent, DraftStore, VariantDraft


def _variant(number: int, *, preferred: bool = False) -> VariantDraft:
    return VariantDraft(
        variant_id=f"u-043c-v{number}",
        sample_id=f"sample-{number}",
        capture_sha256=f"{number:064x}",
        label="м",
        context_tag="isolated",
        preferred=preferred,
        history=(DraftEvent(revision=1, action="captured", occurred_at_utc="2026-10-14T10:00:00Z"),),
    )


def test_variant_catalog_preserves_history_preference_and_tombstones(tmp_path) -> None:
    store = DraftStore(tmp_path)
    catalog = DraftCatalog(style_id="personal", display_name="Personal", variants=(_variant(1), _variant(2), _variant(3)))
    catalog = catalog.set_preferred("u-043c-v2", "2026-10-14T10:01:00Z")
    catalog = catalog.update_status("u-043c-v1", "rejected", "2026-10-14T10:02:00Z")
    catalog = catalog.delete_from_draft("u-043c-v3", "2026-10-14T10:03:00Z")

    store.save(catalog)
    reopened = store.load("personal")

    assert reopened == catalog
    assert [item.variant_id for item in reopened.visible_variants("м")] == ["u-043c-v1", "u-043c-v2"]
    assert next(item for item in reopened.variants if item.variant_id == "u-043c-v2").preferred
    assert next(item for item in reopened.variants if item.variant_id == "u-043c-v1").review_status == "rejected"
    deleted = next(item for item in reopened.variants if item.variant_id == "u-043c-v3")
    assert deleted.deleted
    assert deleted.history[-1].action == "deleted"
    assert not list(tmp_path.rglob("*.tmp"))


def test_only_one_preferred_variant_per_label() -> None:
    catalog = DraftCatalog(style_id="personal", display_name="Personal", variants=(_variant(1, preferred=True), _variant(2)))
    updated = catalog.set_preferred("u-043c-v2", "2026-10-14T10:01:00Z")
    assert [item.variant_id for item in updated.variants if item.preferred] == ["u-043c-v2"]

