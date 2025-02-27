"""A collection of helper functions for the interaction with Ghidra."""

import logging
import re

from lego_util.exceptions import (
    ClassOrNamespaceNotFoundInGhidraError,
    TypeNotFoundInGhidraError,
    MultipleTypesFoundInGhidraError,
)
from lego_util.globals import GLOBALS

# Disable spurious warnings in vscode / pylance
# pyright: reportMissingModuleSource=false

from ghidra.program.flatapi import FlatProgramAPI
from ghidra.program.model.data import DataType, DataTypeConflictHandler, PointerDataType
from ghidra.program.model.symbol import Namespace

logger = logging.getLogger(__name__)


def get_ghidra_type(api: FlatProgramAPI, type_name: str):
    """
    Searches for the type named `typeName` in Ghidra.

    Raises:
    - NotFoundInGhidraError
    - MultipleTypesFoundInGhidraError
    """
    result = api.getDataTypes(type_name)
    if len(result) == 0:
        raise TypeNotFoundInGhidraError(type_name)
    if len(result) == 1:
        return result[0]

    raise MultipleTypesFoundInGhidraError(type_name, result)


def get_or_add_pointer_type(api: FlatProgramAPI, pointee: DataType) -> DataType:
    new_pointer_data_type = PointerDataType(pointee)
    new_pointer_data_type.setCategoryPath(pointee.getCategoryPath())
    return add_data_type_or_reuse_existing(api, new_pointer_data_type)


def add_data_type_or_reuse_existing(
    api: FlatProgramAPI, new_data_type: DataType
) -> DataType:
    result_data_type = (
        api.getCurrentProgram()
        .getDataTypeManager()
        .addDataType(new_data_type, DataTypeConflictHandler.KEEP_HANDLER)
    )
    if result_data_type is not new_data_type:
        logger.debug(
            "Reusing existing data type instead of new one: %s (class: %s)",
            result_data_type,
            result_data_type.__class__,
        )
    return result_data_type


def _get_ghidra_namespace(
    api: FlatProgramAPI, namespace_hierachy: list[str]
) -> Namespace:
    namespace = api.getCurrentProgram().getGlobalNamespace()
    for part in namespace_hierachy:
        if len(part) == 0:
            continue
        namespace = api.getNamespace(namespace, part)
        if namespace is None:
            raise ClassOrNamespaceNotFoundInGhidraError(namespace_hierachy)
    return namespace


def _create_ghidra_namespace(
    api: FlatProgramAPI, namespace_hierachy: list[str]
) -> Namespace:
    namespace = api.getCurrentProgram().getGlobalNamespace()
    for part in namespace_hierachy:
        if len(part) == 0:
            continue
        namespace = api.getNamespace(namespace, part)
        if namespace is None:
            namespace = api.createNamespace(namespace, part)
    return namespace


def get_or_create_namespace(
    api: FlatProgramAPI, class_name_with_namespace: str
) -> Namespace:
    colon_split = class_name_with_namespace.split("::")
    class_name = colon_split[-1]
    logger.info("Looking for namespace: '%s'", class_name_with_namespace)
    try:
        result = _get_ghidra_namespace(api, colon_split)
        logger.debug("Found existing class/namespace %s", class_name_with_namespace)
        return result
    except ClassOrNamespaceNotFoundInGhidraError:
        logger.info("Creating class/namespace %s", class_name_with_namespace)
        class_name = colon_split.pop()
        parent_namespace = _create_ghidra_namespace(api, colon_split)
        return api.createClass(parent_namespace, class_name)


# These appear in debug builds
THUNK_OF_RE = re.compile(r"^Thunk of '(.*)'$")


def sanitize_name(name: str) -> str:
    """
    Takes a full class or function name and replaces characters not accepted by Ghidra.
    Applies mostly to templates, names like `vbase destructor`, and thunks in debug build.
    """
    if (match := THUNK_OF_RE.fullmatch(name)) is not None:
        is_thunk = True
        name = match.group(1)
    else:
        is_thunk = False

    # Replace characters forbidden in Ghidra
    new_name = (
        name.replace("<", "[")
        .replace(">", "]")
        .replace("*", "#")
        .replace(" ", "_")
        .replace("`", "'")
    )

    # Importing function names like `FUN_10001234` into BETA10 can be confusing
    # because Ghidra's auto-generated functions look exactly the same.
    # Therefore, such function names are replaced by `LEGO_10001234` in the BETA10 import.

    # FIXME: The identification here is a crutch - we need a more reusable solution for this scenario
    if GLOBALS.target_name.upper() == "BETA10.DLL":
        new_name = re.sub(r"FUN_([0-9a-f]{8})", r"LEGO1_\1", new_name)

    if "<" in name:
        new_name = "_template_" + new_name

    if is_thunk:
        split = new_name.split("::")
        split[-1] = "_thunk_" + split[-1]
        new_name = "::".join(split)

    if new_name != name:
        logger.info(
            "Changed class or function name from '%s' to '%s' to avoid Ghidra issues",
            name,
            new_name,
        )
    return new_name


def get_namespace_and_name(api: FlatProgramAPI, name: str) -> tuple[Namespace, str]:
    colon_split = sanitize_name(name).split("::")
    name = colon_split.pop()
    namespace = get_or_create_namespace(api, "::".join(colon_split))
    return namespace, name
