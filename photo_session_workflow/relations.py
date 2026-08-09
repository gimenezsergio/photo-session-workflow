"""Pure, deterministic relations between admitted inventory entries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import quote

from .inventory import InventoryEntry, InventoryResult


ROLE_BY_EXTENSION = {
    ".nef": "raw",
    ".jpg": "image",
    ".jpeg": "image",
    ".xmp": "sidecar",
    ".acr": "auxiliary",
}
ROLE_ORDER = {"raw": 0, "image": 1, "sidecar": 2, "auxiliary": 3}


class RelationInputError(ValueError):
    """Raised for an invalid inventory entry without echoing its path."""


@dataclass(frozen=True, slots=True)
class AssetComponent:
    """A component and its exact provenance in the admitted inventory."""

    role: str
    source_entry: InventoryEntry


@dataclass(frozen=True, slots=True)
class LogicalAsset:
    """One logical asset formed from a normalized directory/base-name key."""

    asset_id: str
    relative_directory: str
    normalized_base_name: str
    original_base_names: tuple[str, ...]
    components: tuple[AssetComponent, ...]
    status: str
    warnings: tuple[str, ...]

    def components_for(self, role: str) -> tuple[AssetComponent, ...]:
        """Return components for one role without changing their stable order."""

        return tuple(component for component in self.components if component.role == role)


@dataclass(frozen=True, slots=True)
class RelationResult:
    """Immutable aggregate with counts and admitted-entry coverage."""

    assets: tuple[LogicalAsset, ...]
    total_assets: int
    complete_count: int
    incomplete_count: int
    ambiguous_count: int
    admitted_entry_count: int
    represented_entry_count: int
    coverage_complete: bool


def _validated_parts(entry: InventoryEntry) -> tuple[str, str, str]:
    if entry.status != "admitted":
        raise RelationInputError("relations require admitted inventory entries")
    relative = PurePosixPath(entry.relative_path)
    windows_relative = PureWindowsPath(entry.relative_path)
    if (
        not entry.relative_path
        or relative.is_absolute()
        or windows_relative.is_absolute()
        or bool(windows_relative.drive)
        or "\\" in entry.relative_path
        or ".." in relative.parts
        or relative.name != entry.filename
    ):
        raise RelationInputError("inventory entry path must be a valid relative path")
    role = ROLE_BY_EXTENSION.get(entry.normalized_extension)
    if role is None:
        raise RelationInputError("inventory entry extension is not supported")
    if PurePosixPath(entry.filename).suffix.casefold() != entry.normalized_extension:
        raise RelationInputError("inventory entry extension metadata is inconsistent")
    base_name = entry.filename[: -len(PurePosixPath(entry.filename).suffix)]
    if not base_name:
        raise RelationInputError("inventory entry base name must not be empty")
    directory = relative.parent.as_posix()
    return directory, base_name, role


def _asset_id(directory: str, normalized_base_name: str) -> str:
    encoded_directory = quote(directory, safe="")
    encoded_base = quote(normalized_base_name, safe="")
    return f"asset:{encoded_directory}:{encoded_base}"


def _asset_sort_key(asset: LogicalAsset) -> tuple[str, str, str]:
    return (
        asset.relative_directory.casefold(),
        asset.relative_directory,
        asset.normalized_base_name,
    )


def _component_sort_key(component: AssetComponent) -> tuple[int, str, str]:
    relative = component.source_entry.relative_path
    return ROLE_ORDER[component.role], relative.casefold(), relative


def relate_inventory(inventory: InventoryResult) -> RelationResult:
    """Relate admitted entries by directory and case-folded final-extension stem."""

    groups: dict[tuple[str, str], list[tuple[str, AssetComponent]]] = {}
    for entry in inventory.entries:
        directory, original_base_name, role = _validated_parts(entry)
        key = directory, original_base_name.casefold()
        groups.setdefault(key, []).append(
            (original_base_name, AssetComponent(role=role, source_entry=entry))
        )

    assets: list[LogicalAsset] = []
    for (directory, normalized_base_name), candidates in groups.items():
        original_base_names = tuple(
            sorted(
                {base_name for base_name, _ in candidates},
                key=lambda value: (value.casefold(), value),
            )
        )
        components = tuple(
            sorted((component for _, component in candidates), key=_component_sort_key)
        )
        role_counts = {
            role: sum(component.role == role for component in components)
            for role in ROLE_ORDER
        }

        warnings: list[str] = []
        ambiguous = False
        if len(original_base_names) > 1:
            warnings.append("base_name_case_collision")
            ambiguous = True
        for role in ROLE_ORDER:
            if role_counts[role] > 1:
                warnings.append(f"multiple_{role}_candidates")
                ambiguous = True

        has_photo = bool(role_counts["raw"] or role_counts["image"])
        if not role_counts["sidecar"]:
            warnings.append("xmp_missing")
        if has_photo and not role_counts["raw"]:
            warnings.append("raw_missing")
        if has_photo and not role_counts["image"]:
            warnings.append("image_missing")
        if not has_photo:
            warnings.append("photographic_file_missing")

        if ambiguous:
            status = "ambiguous"
        elif has_photo:
            status = "complete"
        else:
            status = "incomplete"

        assets.append(
            LogicalAsset(
                asset_id=_asset_id(directory, normalized_base_name),
                relative_directory=directory,
                normalized_base_name=normalized_base_name,
                original_base_names=original_base_names,
                components=components,
                status=status,
                warnings=tuple(warnings),
            )
        )

    assets.sort(key=_asset_sort_key)
    represented = sum(len(asset.components) for asset in assets)
    admitted = len(inventory.entries)
    return RelationResult(
        assets=tuple(assets),
        total_assets=len(assets),
        complete_count=sum(asset.status == "complete" for asset in assets),
        incomplete_count=sum(asset.status == "incomplete" for asset in assets),
        ambiguous_count=sum(asset.status == "ambiguous" for asset in assets),
        admitted_entry_count=admitted,
        represented_entry_count=represented,
        coverage_complete=represented == admitted,
    )
