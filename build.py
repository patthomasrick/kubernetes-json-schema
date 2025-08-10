import json
import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List
from urllib import request

# Set up default logger
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


KUBERNETES_GIT_URL = "https://raw.githubusercontent.com/kubernetes/kubernetes"
SCHEMA_REF_BASE_URL = "https://patthomasrick.github.io/kubernetes-json-schema"
DOCKER_IMAGE_TAG = "patthomasrick/openapi2jsonschema:latest"
EARLIEST_API_VERSION = "v1.7.0"
LATEST_API_VERSION = "v2.0.0"


def version_compare(v1: str, v2: str) -> int:
    v1_parts = list(map(int, v1.strip("v").split(".")))
    v2_parts = list(map(int, v2.strip("v").split(".")))

    while len(v1_parts) < len(v2_parts):
        v1_parts.append(0)
    while len(v2_parts) < len(v1_parts):
        v2_parts.append(0)

    for part1, part2 in zip(v1_parts, v2_parts):
        if part1 < part2:
            return -1
        elif part1 > part2:
            return 1
    return 0


def get_kubernetes_api_versions() -> List[str]:
    """Fetches the list of Kubernetes API versions from GitHub tags."""

    url = "https://api.github.com/repos/kubernetes/kubernetes/git/refs/tags"
    with request.urlopen(url) as response:
        data = response.read()
    tags = json.loads(data)
    tag_refs = [tag["ref"][len("refs/tags/") :] for tag in tags if tag["ref"].startswith("refs/tags/v1")]

    logging.info(f"Found {len(tag_refs)} Kubernetes API versions.")
    logging.debug(f"Kubernetes API versions: {tag_refs}")

    return tag_refs


def openapi2jsonschema(*args: str):
    """Runs the openapi2jsonschema command in a Docker container."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{os.getcwd()}:/workdir",
        "-w",
        "/workdir",
        "-u",
        f"{os.getuid()}:{os.getgid()}",
        DOCKER_IMAGE_TAG,
        "openapi2jsonschema",
    ] + list(args)
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"Successfully ran openapi2jsonschema with args: {args}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running openapi2jsonschema: {e}, command: {' '.join(cmd)}, output: {e.output}")
        raise e

    # Run jq to sort all outputted JSON files in the current directory
    output_dir = args[1]
    num_sorted = 0
    for file in os.listdir(output_dir):
        if file.endswith(".json"):
            file_path = os.path.join(output_dir, file)
            try:
                with open(file_path, "r") as infile:
                    result = subprocess.run(
                        ["jq", "--sort-keys", "."],
                        stdin=infile,
                        stdout=subprocess.PIPE,
                        check=True,
                        text=True,
                    )
                with open(file_path, "w") as outfile:
                    outfile.write(result.stdout)
                num_sorted += 1
            except subprocess.CalledProcessError as e:
                logger.error(f"jq failed to sort {file}: {e}")

    logger.info(f"Sorted {num_sorted} JSON files in {output_dir}")

    return result.stdout


def version_to_path(v: str) -> Path:
    return Path("kubernetes-api")


def copy_latest_patch_versions_to_minor(versions: List[str]):
    minor_version_to_latest_patch: Dict[str, str] = {}
    patch_version_to_minor_version: Dict[str, str] = {}
    patch_version_to_path: Dict[str, Path] = {}

    for v in versions:
        v_path = version_to_path(v) / v
        if not v_path.exists():
            continue

        minor_version = ".".join(v.split(".")[:2])
        patch_version_to_minor_version[v] = minor_version
        patch_version_to_path[v] = v_path
        if minor_version not in minor_version_to_latest_patch:
            minor_version_to_latest_patch[minor_version] = v
        else:
            if version_compare(v, minor_version_to_latest_patch[minor_version]) > 0:
                minor_version_to_latest_patch[minor_version] = v

    logger.info(f"Minor version to latest patch mapping: {minor_version_to_latest_patch}")

    for minor_version, latest_patch in minor_version_to_latest_patch.items():
        latest_patch_path = patch_version_to_path[latest_patch]
        minor_version_path = version_to_path(minor_version) / minor_version

        if minor_version_path.exists():
            subprocess.run(["rm", "-rf", str(minor_version_path)], check=True)

        subprocess.run(
            ["cp", "-r", str(latest_patch_path) + "/", str(minor_version_path) + "/"],
            check=True,
        )

        logger.info(f"Copied latest patch version {latest_patch} to minor version {minor_version}")


def main():
    """Main function to build JSON schemas for Kubernetes versions."""

    versions = get_kubernetes_api_versions()
    versions = [
        v
        for v in versions
        if "-" not in v
        and version_compare(v, EARLIEST_API_VERSION) >= 0
        and version_compare(v, LATEST_API_VERSION) <= 0
    ]
    versions.sort(key=lambda v: list(map(int, v.strip("v").split("."))))
    logger.info(f"Filtered Kubernetes API versions: {versions}")

    versions += ["master"]

    # Remove existing master directory if it exists
    master_path = version_to_path("master") / "master"
    if master_path.exists():
        logger.info(f"Removing existing master directory: {master_path}")
        subprocess.run(["rm", "-rf", str(master_path)], check=True)

    with ThreadPoolExecutor() as tpe:
        futures = []
        for version in versions:
            out_path = version_to_path(version)
            if not out_path.exists():
                out_path.mkdir(parents=True, exist_ok=True)

            out_path_version = out_path / version
            if out_path_version.exists() and version not in {"master"}:
                logger.warning(f"Output path {out_path_version} already exists. Skipping version {version}.")
                continue

            schema = f"{KUBERNETES_GIT_URL}/{version}/api/openapi-spec/swagger.json"
            # futures.append(
            #     tpe.submit(
            #         openapi2jsonschema,
            #         "-o",
            #         f"{str(out_path)}/{version}-standalone-strict",
            #         "--expanded",
            #         "--kubernetes",
            #         "--stand-alone",
            #         "--strict",
            #         schema,
            #     )
            # )
            # futures.append(
            #     tpe.submit(
            #         openapi2jsonschema,
            #         "-o",
            #         f"{str(out_path)}/{version}-standalone",
            #         "--expanded",
            #         "--kubernetes",
            #         "--stand-alone",
            #         schema,
            #     )
            # )
            # futures.append(
            #     tpe.submit(
            #         openapi2jsonschema,
            #         "-o",
            #         f"{str(out_path)}/{version}-local",
            #         "--expanded",
            #         "--kubernetes",
            #         schema,
            #     )
            # )
            futures.append(
                tpe.submit(
                    openapi2jsonschema,
                    "-o",
                    f"{str(out_path)}/{version}",
                    "--strict",
                    "--expanded",
                    "--kubernetes",
                    "--prefix",
                    f"{SCHEMA_REF_BASE_URL}/{version}/_definitions.json",
                    schema,
                )
            )

        # for version in versions:
        #     out_path = version_to_path(version)
        #     if not out_path.exists():
        #         out_path.mkdir(parents=True, exist_ok=True)

        #     schema = f"{KUBERNETES_GIT_URL}/{version}/api/openapi-spec/swagger.json"
        #     # futures.append(
        #     #     tpe.submit(
        #     #         openapi2jsonschema,
        #     #         "-o",
        #     #         f"{str(out_path)}/{version}-standalone-strict",
        #     #         "--kubernetes",
        #     #         "--stand-alone",
        #     #         "--strict",
        #     #         schema,
        #     #     )
        #     # )
        #     # futures.append(
        #     #     tpe.submit(
        #     #         openapi2jsonschema,
        #     #         "-o",
        #     #         f"{str(out_path)}/{version}-standalone",
        #     #         "--kubernetes",
        #     #         "--stand-alone",
        #     #         schema,
        #     #     )
        #     # )
        #     # futures.append(
        #     #     tpe.submit(
        #     #         openapi2jsonschema,
        #     #         "-o",
        #     #         f"{str(out_path)}/{version}-local",
        #     #         "--kubernetes",
        #     #         schema,
        #     #     )
        #     # )
        #     futures.append(
        #         tpe.submit(
        #             openapi2jsonschema,
        #             "-o",
        #             f"{str(out_path)}/{version}",
        #             "--kubernetes",
        #             "--prefix",
        #             f"{SCHEMA_REF_BASE_URL}/{str(out_path)}/{version}/_definitions.json",
        #             schema,
        #         )
        #     )

        for future in as_completed(futures):
            try:
                future.result()
            except subprocess.CalledProcessError as e:
                logger.error(f"Error processing version: {e}")
            else:
                logger.info("Successfully processed a version.")

    logger.info("All patch versions processed successfully.")

    copy_latest_patch_versions_to_minor([v for v in versions if v not in {"master"}])


if __name__ == "__main__":
    main()
