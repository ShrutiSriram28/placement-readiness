from __future__ import annotations

import ast
import json
import multiprocessing as mp
from typing import Any

from fastapi import FastAPI
from pydantic import (
    BaseModel,
    Field,
)


app = FastAPI(
    title=(
        "Placement Readiness "
        "Code Runner"
    )
)


class TestInput(BaseModel):
    args: list[Any]


class GradedTest(
    TestInput
):
    expected: Any


class DeriveRequest(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=20000,
    )

    function_name: str = Field(
        min_length=1,
        max_length=100,
    )

    tests: list[
        TestInput
    ] = Field(
        min_length=1,
        max_length=50,
    )


class RunRequest(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=20000,
    )

    function_name: str = Field(
        min_length=1,
        max_length=100,
    )

    tests: list[
        GradedTest
    ] = Field(
        min_length=1,
        max_length=50,
    )


FORBIDDEN_NAMES = {
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "__import__",
    "globals",
    "locals",
    "vars",
    "breakpoint",
}


FORBIDDEN_NODE_TYPES = (
    ast.Import,
    ast.ImportFrom,
    ast.With,
    ast.AsyncWith,
    ast.Lambda,
    ast.ClassDef,
    ast.Global,
    ast.Nonlocal,
)


SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}


def _validate_source(
    code: str,
    function_name: str,
) -> None:
    try:
        tree = ast.parse(
            code
        )

    except SyntaxError as exc:
        raise ValueError(
            (
                "Syntax error: "
                f"{exc}"
            )
        ) from exc

    function_defs = [
        node
        for node
        in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name
        == function_name
    ]

    if not function_defs:
        raise ValueError(
            (
                "Required function "
                f"'{function_name}' "
                "was not defined."
            )
        )

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            FORBIDDEN_NODE_TYPES,
        ):
            raise ValueError(
                (
                    "Disallowed Python "
                    "construct: "
                    f"{type(node).__name__}."
                )
            )

        if (
            isinstance(
                node,
                ast.Name,
            )
            and node.id
            in FORBIDDEN_NAMES
        ):
            raise ValueError(
                (
                    "Disallowed name: "
                    f"{node.id}."
                )
            )

        if (
            isinstance(
                node,
                ast.Attribute,
            )
            and node.attr.startswith(
                "__"
            )
        ):
            raise ValueError(
                (
                    "Dunder attribute "
                    "access is not allowed."
                )
            )


def _json_safe(
    value: Any,
) -> Any:
    try:
        json.dumps(
            value
        )

        return value

    except TypeError as exc:
        raise ValueError(
            (
                "Function returned a "
                "non-JSON-compatible "
                "value: "
                f"{type(value).__name__}."
            )
        ) from exc


def _worker(
    code: str,
    function_name: str,
    tests: list[dict],
    derive: bool,
    queue,
) -> None:
    try:
        _validate_source(
            code,
            function_name,
        )

        namespace = {
            "__builtins__":
                SAFE_BUILTINS
        }

        exec(
            compile(
                code,
                "<submission>",
                "exec",
            ),
            namespace,
            namespace,
        )

        function = namespace.get(
            function_name
        )

        if not callable(
            function
        ):
            raise ValueError(
                (
                    f"'{function_name}' "
                    "is not callable."
                )
            )

        if derive:
            validated_tests = []

            for test in tests:
                args = test.get(
                    "args",
                    [],
                )

                result = (
                    _json_safe(
                        function(
                            *args
                        )
                    )
                )

                validated_tests.append(
                    {
                        "args":
                            args,

                        "expected":
                            result,
                    }
                )

            queue.put(
                {
                    "ok":
                        True,

                    "tests":
                        validated_tests,
                }
            )

            return

        passed = 0
        failures = []

        for (
            index,
            test,
        ) in enumerate(
            tests,
            start=1,
        ):
            args = test.get(
                "args",
                [],
            )

            expected = test.get(
                "expected"
            )

            try:
                actual = (
                    _json_safe(
                        function(
                            *args
                        )
                    )
                )

            except Exception as exc:
                failures.append(
                    {
                        "test":
                            index,

                        "reason":
                            (
                                "Runtime error: "
                                f"{type(exc).__name__}: "
                                f"{exc}"
                            ),
                    }
                )

                continue

            if actual == expected:
                passed += 1

            else:
                # Do not reveal hidden
                # inputs or expected
                # outputs to the student.
                failures.append(
                    {
                        "test":
                            index,

                        "reason":
                            (
                                "Output did not "
                                "match expected "
                                "output."
                            ),
                    }
                )

        queue.put(
            {
                "ok":
                    True,

                "passed":
                    passed,

                "total":
                    len(tests),

                "failures":
                    failures,

                "message":
                    (
                        f"Passed "
                        f"{passed}/"
                        f"{len(tests)} "
                        "hidden tests."
                    ),
            }
        )

    except Exception as exc:
        queue.put(
            {
                "ok":
                    False,

                "passed":
                    0,

                "total":
                    len(tests),

                "failures":
                    [],

                "message":
                    (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
            }
        )


def _execute_with_timeout(
    code: str,
    function_name: str,
    tests: list[dict],
    derive: bool,
    timeout_seconds:
        float = 3.0,
) -> dict:
    ctx = mp.get_context(
        "spawn"
    )

    queue = ctx.Queue()

    process = ctx.Process(
        target=_worker,
        args=(
            code,
            function_name,
            tests,
            derive,
            queue,
        ),
    )

    process.start()

    process.join(
        timeout_seconds
    )

    if process.is_alive():
        process.terminate()
        process.join(
            1
        )

        return {
            "ok":
                False,

            "passed":
                0,

            "total":
                len(tests),

            "failures":
                [],

            "message":
                "Execution timed out.",
        }

    if queue.empty():
        return {
            "ok":
                False,

            "passed":
                0,

            "total":
                len(tests),

            "failures":
                [],

            "message":
                (
                    "Runner process exited "
                    "without a result."
                ),
        }

    return queue.get()


@app.get(
    "/health"
)
def health() -> dict:
    return {
        "status":
            "ok"
    }


@app.post(
    "/derive"
)
def derive(
    request: DeriveRequest,
) -> dict:
    return (
        _execute_with_timeout(
            request.code,
            request.function_name,
            [
                test.model_dump()
                for test
                in request.tests
            ],
            derive=True,
        )
    )


@app.post(
    "/run"
)
def run_code(
    request: RunRequest,
) -> dict:
    return (
        _execute_with_timeout(
            request.code,
            request.function_name,
            [
                test.model_dump()
                for test
                in request.tests
            ],
            derive=False,
        )
    )