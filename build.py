import json
import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List
from urllib import request

# Set up default logger
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


KUBERNETES_GIT_URL = "{KUBERNETES_GIT_URL}"
SCHEMA_REF_BASE_URL = "https://github.com/patthomasrick/kubernetes-json-schema/raw/refs/heads/master/kubernetes-api"
DOCKER_IMAGE_TAG = "openapi2jsonschema:latest"
EARLIEST_API_VERSION = "v1.29.0"
LATEST_API_VERSION = "v1.30.0"


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


def build_openapi2jsonschema_image() -> str:
    """Builds the Docker image for openapi2jsonschema, if it does not already exist."""

    # Check if the image already exists
    try:
        result = subprocess.run(
            ["docker", "images", "-q", DOCKER_IMAGE_TAG],
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            logger.info(f"Docker image {DOCKER_IMAGE_TAG} already exists. Skipping build.")
            return DOCKER_IMAGE_TAG
    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to check for existing Docker image: {e}")

    cwd = os.getcwd()
    docker_dir = os.path.join(cwd, "docker-openapi2jsonschema")
    if not os.path.isdir(docker_dir):
        raise RuntimeError(f"Directory {docker_dir} does not exist")
    os.chdir(docker_dir)
    try:
        subprocess.run(["docker", "build", "-t", DOCKER_IMAGE_TAG, "."], check=True)
    finally:
        os.chdir(cwd)

    return DOCKER_IMAGE_TAG


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
        "openapi2jsonschema:latest",
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
                with open(file_path, "r") as infile, open(f"{file_path}.sorted", "w") as outfile:
                    subprocess.run(["jq", "--sort-keys", "."], stdin=infile, stdout=outfile, check=True)
                    num_sorted += 1
                os.replace(f"{file_path}.sorted", file_path)
            except subprocess.CalledProcessError as e:
                logger.error(f"jq failed to sort {file}: {e}")

    logger.info(f"Sorted {num_sorted} JSON files in {output_dir}")

    return result.stdout


def version_to_path(v: str) -> Path:
    return Path("kubernetes-api")


def main():
    """Main function to build JSON schemas for Kubernetes versions."""

    build_openapi2jsonschema_image()

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

    with ThreadPoolExecutor(max_workers=4) as tpe:
        futures = []
        for version in versions:
            out_path = version_to_path(version)
            if not out_path.exists():
                out_path.mkdir(parents=True, exist_ok=True)

            schema = f"{KUBERNETES_GIT_URL}/{version}/api/openapi-spec/swagger.json"
            prefix = f"{SCHEMA_REF_BASE_URL}/{str(out_path)}/_definitions.json"
            futures.append(
                tpe.submit(
                    openapi2jsonschema,
                    "-o",
                    f"{str(out_path)}/{version}-standalone-strict",
                    "--expanded",
                    "--kubernetes",
                    "--stand-alone",
                    "--strict",
                    schema,
                )
            )
            futures.append(
                tpe.submit(
                    openapi2jsonschema,
                    "-o",
                    f"{str(out_path)}/{version}-standalone",
                    "--expanded",
                    "--kubernetes",
                    "--stand-alone",
                    schema,
                )
            )
            futures.append(
                tpe.submit(
                    openapi2jsonschema,
                    "-o",
                    f"{str(out_path)}/{version}-local",
                    "--expanded",
                    "--kubernetes",
                    schema,
                )
            )
            futures.append(
                tpe.submit(
                    openapi2jsonschema,
                    "-o",
                    f"{str(out_path)}/{version}",
                    "--expanded",
                    "--kubernetes",
                    "--prefix",
                    prefix,
                    schema,
                )
            )

        for version in versions:
            out_path = version_to_path(version)
            if not out_path.exists():
                out_path.mkdir(parents=True, exist_ok=True)

            schema = f"{KUBERNETES_GIT_URL}/{version}/api/openapi-spec/swagger.json"
            prefix = f"{SCHEMA_REF_BASE_URL}/{str(out_path)}/_definitions.json"
            futures.append(
                tpe.submit(
                    openapi2jsonschema,
                    "-o",
                    f"{str(out_path)}/{version}-standalone-strict",
                    "--kubernetes",
                    "--stand-alone",
                    "--strict",
                    schema,
                )
            )
            futures.append(
                tpe.submit(
                    openapi2jsonschema,
                    "-o",
                    f"{str(out_path)}/{version}-standalone",
                    "--kubernetes",
                    "--stand-alone",
                    schema,
                )
            )
            futures.append(
                tpe.submit(
                    openapi2jsonschema,
                    "-o",
                    f"{str(out_path)}/{version}-local",
                    "--kubernetes",
                    schema,
                )
            )
            futures.append(
                tpe.submit(
                    openapi2jsonschema,
                    "-o",
                    f"{str(out_path)}/{version}",
                    "--kubernetes",
                    "--prefix",
                    prefix,
                    schema,
                )
            )

        for future in as_completed(futures):
            try:
                future.result()
            except subprocess.CalledProcessError as e:
                logger.error(f"Error processing version: {e}")
            else:
                logger.info("Successfully processed a version.")


if __name__ == "__main__":
    main()
