import dataiku
from dataiku.customrecipe import (
    get_recipe_config,
    get_input_names_for_role,
    get_output_names_for_role,
)
from dku_io_utils.utils import get_partition_root


class PluginParamValidationError(ValueError):
    """Custom exception raised when the the plugin parameters chosen by the user are invalid"""

    pass


def load_training_config(recipe_config):
    params = {}

    input_dataset_name = get_input_names_for_role("input_dataset")[0]
    params["training_dataset"] = dataiku.Dataset(input_dataset_name)
    training_dataset_columns = [p["name"] for p in params["training_dataset"].read_schema()]
    params["partition_root"] = get_partition_root(params["training_dataset"])

    model_folder_name = get_output_names_for_role("model_folder")[0]
    params["model_folder"] = dataiku.Folder(model_folder_name)

    evaluation_dataset_name = get_output_names_for_role("evaluation_dataset")[0]
    params["evaluation_dataset"] = dataiku.Dataset(evaluation_dataset_name)

    params["make_forecasts"] = False
    evaluation_forecasts_names = get_output_names_for_role("evaluation_forecasts")
    if len(evaluation_forecasts_names) > 0:
        params["evaluation_forecasts"] = dataiku.Dataset(evaluation_forecasts_names[0])
        params["make_forecasts"] = True

    params["time_column_name"] = recipe_config.get("time_column")
    if params["time_column_name"] not in training_dataset_columns:
        raise PluginParamValidationError("Invalid time column selection")

    params["target_columns_names"] = recipe_config.get("target_columns")
    if len(params["target_columns_names"]) == 0 or not all(column in training_dataset_columns for column in params["target_columns_names"]):
        raise PluginParamValidationError("Invalid target column(s) selection")

    params["timeseries_identifiers_names"] = recipe_config.get("timeseries_identifiers", [])
    if not all(column in training_dataset_columns for column in params["timeseries_identifiers_names"]):
        raise PluginParamValidationError("Invalid timeseries identifiers column(s) selection")

    params["external_features_columns_names"] = recipe_config.get("external_feature_columns", [])
    if not all(column in training_dataset_columns for column in params["external_features_columns_names"]):
        raise PluginParamValidationError("Invalid external features column(s) selection")

    params["deepar_model_activated"] = recipe_config.get("deepar_model_activated", False)
    params["time_granularity_unit"] = recipe_config.get("time_granularity_unit")

    params["time_granularity_step"] = recipe_config.get("time_granularity_step")
    if params["time_granularity_step"] is None:
        raise PluginParamValidationError("Time granularity step is not set.")

    params["frequency"] = "{}{}".format(params["time_granularity_step"], params["time_granularity_unit"])

    params["columns_to_keep"] = (
        [params["time_column_name"]] + params["target_columns_names"] + params["timeseries_identifiers_names"] + params["external_features_columns_names"]
    )

    params["prediction_length"] = recipe_config.get("prediction_length")
    if params["prediction_length"] is None:
        raise PluginParamValidationError("Prediction length is not set.")

    params["context_length"] = recipe_config.get("context_length", 0)
    if params["context_length"] == 0:
        params["context_length"] = params["prediction_length"]

    params["epoch"] = recipe_config.get("epoch", 1)
    params["batch_size"] = recipe_config.get("batch_size", 32)
    params["gpu"] = recipe_config.get("gpu", "no_gpu")  # V2 implement

    params["evaluation_strategy"] = recipe_config.get("evaluation_strategy", "split")
    params["evaluation_only"] = recipe_config.get("evaluation_only", False)

    return params


def load_predict_config():
    params = {}
    recipe_config = get_recipe_config()

    # input folder
    model_folder = dataiku.Folder(get_input_names_for_role("model_folder")[0])
    params["model_folder"] = model_folder

    params["external_features_future_dataset"] = None
    external_features_future_dataset_names = get_input_names_for_role("external_features_future_dataset")
    if len(external_features_future_dataset_names) > 0:
        params["external_features_future_dataset"] = dataiku.Dataset(external_features_future_dataset_names[0])

    # output dataset
    output_dataset_names = get_output_names_for_role("output_dataset")
    if len(output_dataset_names) == 0:
        raise PluginParamValidationError("Please specify output dataset")
    params["output_dataset"] = dataiku.Dataset(output_dataset_names[0])
    params["partition_root"] = get_partition_root(params["output_dataset"])

    params["manual_selection"] = True if recipe_config.get("model_selection_mode") == "manual" else False

    params["performance_metric"] = recipe_config.get("performance_metric")
    params["selected_session"] = recipe_config.get("manually_selected_session")
    params["selected_model_label"] = recipe_config.get("manually_selected_model_label")

    params["prediction_length"] = recipe_config.get("prediction_length")
    params["quantiles"] = recipe_config.get("quantiles")
    if any(x < 0 or x > 1 for x in params["quantiles"]):
        raise PluginParamValidationError("Quantiles must be between 0 and 1.")
    params["quantiles"].sort()

    params["include_history"] = recipe_config.get("include_history")

    return params
