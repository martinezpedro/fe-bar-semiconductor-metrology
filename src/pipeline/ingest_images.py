"""Lakeflow Declarative Pipeline: image + sidecar intake with validation.

bronze_image_files     Auto Loader (binaryFile) over the landing Volume. Keeps
                       file facts, a SHA-256 content hash and a decode check;
                       image bytes stay in the Volume, not in Delta.
bronze_image_metadata  Auto Loader (json) over the sidecar files.
image_catalog          One governed row per unique image (dedup by hash),
                       joined to its metadata. Expectations enforce format,
                       decodability and metadata presence.
image_quarantine       Everything that failed a check, with the reason.
"""
import io
import re

import dlt
import pandas as pd
from pyspark.sql import functions as F
from pyspark.sql import types as T
from pyspark.sql.window import Window

LANDING = spark.conf.get("fabs.landing_path")

decode_schema = T.StructType(
    [
        T.StructField("decodable", T.BooleanType()),
        T.StructField("width", T.IntegerType()),
        T.StructField("height", T.IntegerType()),
        T.StructField("pil_mode", T.StringType()),
        T.StructField("decode_error", T.StringType()),
    ]
)


@F.pandas_udf(decode_schema)
def decode_check(content: pd.Series) -> pd.DataFrame:
    from PIL import Image

    rows = []
    for b in content:
        try:
            with Image.open(io.BytesIO(b)) as im:
                im.load()
                rows.append((True, im.width, im.height, im.mode, None))
        except Exception as e:  # corrupt / truncated / not an image
            msg = re.sub(r"\s*<[^>]*>", "", str(e))  # drop object reprs like <_io.BytesIO at 0x..>
            rows.append((False, None, None, None, msg[:200]))
    return pd.DataFrame(rows, columns=[f.name for f in decode_schema.fields])


@dlt.table(comment="Raw image file facts from the landing Volume (no image bytes).")
def bronze_image_files():
    df = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "binaryFile")
        .option("pathGlobFilter", "*.{tif,tiff,TIF,TIFF,jpg,jpeg,JPG,JPEG}")
        .option("recursiveFileLookup", "true")
        .load(LANDING)
    )
    return (
        df.withColumn("check", decode_check("content"))
        .select(
            F.regexp_replace("path", "^dbfs:", "").alias("file_path"),
            F.regexp_extract("path", r"([^/]+)\.[^./]+$", 1).alias("image_id"),
            F.lower(F.regexp_extract("path", r"\.([^./]+)$", 1)).alias("file_ext"),
            F.col("length").alias("size_bytes"),
            F.col("modificationTime").alias("file_modified_ts"),
            F.sha2("content", 256).alias("sha256"),
            "check.*",
            F.current_timestamp().alias("ingested_ts"),
        )
    )


@dlt.table(comment="Raw sidecar metadata (one JSON per image).")
def bronze_image_metadata():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaHints", "submission_id STRING, uploaded_by STRING, batch_id STRING, die_x INT, die_y INT, capture_ts TIMESTAMP, gt_defect_type STRING, gt_cd_nm DOUBLE, pixel_size_nm DOUBLE, target_cd_nm DOUBLE, expected_holes INT")
        .option("pathGlobFilter", "*.json")
        .option("recursiveFileLookup", "true")
        .load(LANDING)
        .withColumn("sidecar_path", F.regexp_replace(F.col("_metadata.file_path"), "^dbfs:", ""))
    )


def _joined():
    files = dlt.read("bronze_image_files")
    meta = dlt.read("bronze_image_metadata").drop("_rescued_data")
    # first copy of each content hash wins; later copies are duplicates
    w = Window.partitionBy("sha256").orderBy("file_modified_ts", "file_path")
    return (
        files.withColumn("dup_rank", F.row_number().over(w))
        .join(meta.drop("file_name"), "image_id", "left")
        .withColumn(
            "reject_reason",
            F.when(~F.col("file_ext").isin("tif", "tiff", "jpg", "jpeg"), "unsupported_format")
            .when(~F.col("decodable"), F.concat(F.lit("corrupt: "), F.col("decode_error")))
            .when(F.col("experiment_id").isNull(), "missing_metadata")
            .when(F.col("dup_rank") > 1, "duplicate_content"),
        )
    )


@dlt.table(
    comment="Governed catalog of valid, unique metrology images with context metadata.",
    table_properties={"delta.enableChangeDataFeed": "true"},
)
@dlt.expect_all_or_drop(
    {
        "supported_format": "file_ext IN ('tif','tiff','jpg','jpeg')",
        "decodable": "decodable",
        "has_metadata": "experiment_id IS NOT NULL",
        "unique_content": "dup_rank = 1",
    }
)
def image_catalog():
    return _joined().drop("reject_reason", "decode_error")


@dlt.table(comment="Files rejected by intake validation, with reason.")
def image_quarantine():
    return _joined().where("reject_reason IS NOT NULL").select(
        "file_path", "image_id", "file_ext", "size_bytes", "sha256", "reject_reason", "ingested_ts"
    )
