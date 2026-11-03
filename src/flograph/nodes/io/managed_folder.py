"""Managed Folder

Upload or drop files onto this card to carry their original bytes inside the
project. Connect Upload to Managed Folder to incoming, and folder to a
Read Managed File node. Selection in the card is for browsing only.
"""
NODE = {
    "label": "Managed Folder", "category": "IO", "version": "1.8",
    "card": "managed_folder",
    "inputs": [("incoming", "object", {"optional": True,
                "suggest": ["flograph.io.upload_managed_file"]})],
    "outputs": [("folder", "object"), ("files", "dataframe")],
}
PARAMS = [
    {"name": "_managed_metadata", "type": "text", "hidden": True, "default": {}},
    {"name": "metadata_fields", "type": "text", "hidden": True, "default": []},
    {"name": "visible_columns", "type": "string", "label": "Visible file columns",
     "default": "filename, extension, size_bytes, source_modified", "cosmetic": True},
    {"name": "_managed_files", "type": "text", "hidden": True, "default": {}},
    {"name": "width", "type": "int", "default": 460, "min": 300, "max": 1200, "cosmetic": True},
    {"name": "height", "type": "int", "default": 320, "min": 200, "max": 1000, "cosmetic": True},
]


def run(ctx, incoming=None):
    from flograph.core.managed_folder import ManagedFolder
    folder = ManagedFolder.from_params(ctx.params)
    if incoming is not None:
        folder = folder.merged(incoming)
    return {"folder": folder, "files": folder.file_table(ctx.params.get("metadata_fields", []))}
