"""Endpoints of the ``/folders`` resource.

Folders group recordings for whoever is browsing them and exist only in the
index — no directory is ever created, moved or removed on their account. That
is what lets a folder be created empty and sit there until something is filed
into it, and what makes moving a recording a matter of one row.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from api.dependencies import Memory
from api.schemas import FolderCreate, FolderOut, FolderUpdate, folder_ref

router = APIRouter(prefix="/folders", tags=["folders"])


@router.post(
    "",
    response_model=FolderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a folder",
)
def create_folder(memory: Memory, payload: FolderCreate) -> FolderOut:
    """Create an empty folder.

    Args:
        memory: Storage the folder is written to.
        payload: Name of the folder and, optionally, where to put it.

    Returns:
        The folder as it was stored, empty.

    Raises:
        HTTPException: 404 if the parent does not exist, 409 if a sibling
            already carries that name.
    """
    folder = memory.create_folder(payload.name, parent_id=folder_ref(payload.parent))
    return FolderOut.from_folder(folder)


@router.get(
    "",
    response_model=list[FolderOut],
    summary="List the folders",
)
def list_folders(
    memory: Memory,
    parent: Annotated[
        str | None,
        Query(description="Look inside this folder. Absent: the whole tree."),
    ] = None,
) -> list[FolderOut]:
    """List the folders, with how many recordings each one holds.

    Without ``parent`` the whole tree travels in one response, which is what a
    sidebar wants: folders are few and human made, so nesting them client side
    costs less than one request per level.

    Args:
        memory: Storage the folders are read from.
        parent: Folder to look into, ``root`` for the top level. When absent
            every folder is returned.

    Returns:
        The matching folders, ordered by name.

    Raises:
        HTTPException: 404 if ``parent`` does not exist.
    """
    if parent is None:
        folders = memory.all_folders()
    else:
        parent_id = folder_ref(parent)
        if parent_id is not None:
            memory.get_folder(parent_id)
        folders = memory.list_folders(parent_id)

    counts = memory.folder_counts()
    return [
        FolderOut.from_folder(folder, recordings=counts.get(folder.id, 0))
        for folder in folders
    ]


@router.get(
    "/{folder_id}",
    response_model=FolderOut,
    summary="Read a folder",
)
def get_folder(memory: Memory, folder_id: str) -> FolderOut:
    """Return one folder.

    Raises:
        HTTPException: 404 if the folder does not exist.
    """
    folder = memory.get_folder(folder_id)
    counts = memory.folder_counts()
    return FolderOut.from_folder(folder, recordings=counts.get(folder.id, 0))


@router.get(
    "/{folder_id}/path",
    response_model=list[FolderOut],
    summary="Return the path of a folder",
)
def get_folder_path(memory: Memory, folder_id: str) -> list[FolderOut]:
    """Return the folders leading to this one, top level first.

    The last element is the folder itself, so the result reads as a
    breadcrumb.

    Raises:
        HTTPException: 404 if the folder does not exist.
    """
    return [FolderOut.from_folder(folder) for folder in memory.folder_path(folder_id)]


@router.patch(
    "/{folder_id}",
    response_model=FolderOut,
    summary="Rename or move a folder",
)
def update_folder(memory: Memory, folder_id: str, payload: FolderUpdate) -> FolderOut:
    """Rename a folder, move it, or both at once.

    Nothing below the folder is rewritten: the tree stores pointers, so a
    branch of any size moves as one row. Both changes share a transaction, so
    a rejected move never leaves a rename behind.

    Args:
        memory: Storage the folder lives in.
        folder_id: Folder to change.
        payload: New name and destination. Omitted fields are left alone.

    Returns:
        The folder as it now stands.

    Raises:
        HTTPException: 404 if the folder or the destination does not exist,
            409 if the name is taken, 400 if the move would put the folder
            inside its own subtree.
    """
    with memory.database.transaction():
        folder = memory.get_folder(folder_id)
        if payload.name is not None:
            folder = memory.rename_folder(folder_id, payload.name)
        if payload.parent is not None:
            folder = memory.move_folder(folder_id, folder_ref(payload.parent))

    counts = memory.folder_counts()
    return FolderOut.from_folder(folder, recordings=counts.get(folder.id, 0))


@router.delete(
    "/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a folder",
)
def delete_folder(
    memory: Memory,
    folder_id: str,
    recursive: Annotated[
        bool,
        Query(description="Delete the subfolders and the recordings as well."),
    ] = False,
) -> Response:
    """Delete a folder, refusing by default to take anything down with it.

    Args:
        memory: Storage the folder lives in.
        folder_id: Folder to delete.
        recursive: When true the subfolders and the recordings below are
            deleted as well, media included.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: 404 if the folder does not exist, 409 if it still holds
            something and ``recursive`` is false.
    """
    memory.delete_folder(folder_id, recursive=recursive)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
