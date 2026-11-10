from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from comicapi import merge, utils
from comicapi.comicarchive import ComicArchive
from comicapi.genericmetadata import GenericMetadata
from comictaggerlib import ctversion
from comictaggerlib.cbltransformer import CBLTransformer
from comictaggerlib.ctsettings.settngs_namespace import SettngsNS
from comictalker.talker_utils import cleanup_html


def prepare_metadata(md: GenericMetadata, new_md: GenericMetadata, config: SettngsNS) -> GenericMetadata:
    if config.Metadata_Options__apply_transform_on_import:
        new_md = CBLTransformer(new_md, config).apply()

    final_md = md.copy()
    if config.Auto_Tag__clear_tags:
        final_md = GenericMetadata()

    final_md.overlay(new_md, config.Metadata_Options__metadata_merge, config.Metadata_Options__metadata_merge_lists)

    issue_id = ""
    if final_md.issue_id:
        issue_id = f" [Issue ID {final_md.issue_id}]"

    origin = ""
    if final_md.data_origin is not None:
        origin = f" using info from {final_md.data_origin.name}"
    notes = f"Tagged with ComicTagger {ctversion.version}{origin} on {datetime.now():%Y-%m-%d %H:%M:%S}.{issue_id}"

    if config.Auto_Tag__auto_imprint:
        final_md.fix_publisher()

    return final_md.replace(
        is_empty=False,
        notes=utils.combine_notes(final_md.notes, notes, "Tagged with ComicTagger"),
        description=cleanup_html(final_md.description, config.Metadata_Options__remove_html_tables) or None,
    )


def read_selected_tags(
    tag_ids: list[str], ca: ComicArchive, mode: merge.Mode = merge.Mode.OVERLAY, merge_lists: bool = False
) -> tuple[GenericMetadata, list[str], Exception | None]:
    md = GenericMetadata()
    error = None
    tags_used = []
    try:
        for tag_id in tag_ids:
            metadata = ca.read_tags(tag_id)
            if not metadata.is_empty:
                md.overlay(
                    metadata,
                    mode=mode,
                    merge_lists=merge_lists,
                )
                tags_used.append(tag_id)
    except Exception as e:
        error = e

    return md, tags_used, error


def read_configured_tags(
    ca: ComicArchive, tag_ids: list[str], config: SettngsNS
) -> tuple[GenericMetadata, list[str], Exception | None]:
    return read_selected_tags(tag_ids, ca, config.Metadata_Options__tag_merge, config.Metadata_Options__tag_merge_lists)


def parse_archive_filename(ca: ComicArchive, config: SettngsNS, *, split_words: bool | None = None) -> GenericMetadata:
    return ca.metadata_from_filename(
        parser=config.Filename_Parsing__filename_parser,
        remove_c2c=config.Filename_Parsing__remove_c2c,
        remove_fcbd=config.Filename_Parsing__remove_fcbd,
        remove_publisher=config.Filename_Parsing__remove_publisher,
        split_words=config.Filename_Parsing__split_words if split_words is None else split_words,
        allow_issue_start_with_letter=config.Filename_Parsing__allow_issue_start_with_letter,
        protofolius_issue_number_scheme=config.Filename_Parsing__protofolius_issue_number_scheme,
        publisher_names=utils.publishers,
    )


def write_selected_tags(ca: ComicArchive, md: GenericMetadata, tag_ids: Iterable[str]) -> tuple[list[str], str | None]:
    written: list[str] = []
    for tag_id in tag_ids:
        if not ca.write_tags(md, tag_id):
            return written, tag_id
        written.append(tag_id)
    return written, None
