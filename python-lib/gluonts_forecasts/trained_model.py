import pandas as pd
import numpy as np
from gluonts_forecasts.utils import concat_timeseries_per_identifiers, concat_all_timeseries, add_row_origin
from constants import METRICS_DATASET, METRICS_COLUMNS_DESCRIPTIONS, TIMESERIES_KEYS, ROW_ORIGIN
from gluonts.model.forecast import QuantileForecast
from safe_logger import SafeLogger

logger = SafeLogger("Forecast plugin")


class TrainedModel:
    """
    Wrapper class to make forecasts using a GluonTS Predictor and a training GluonTS ListDataset, and to output a well formatted forecasts dataframe


    Attributes:
        predictor (gluonts.model.predictor.Predictor)
        gluon_dataset (gluonts.dataset.common.ListDataset): GluonTS ListDataset generated by the GluonDataset class (with extra fields to name timeseries)
        prediction_length (int): Number of time steps to predict (at most the prediction length used in training)
        quantiles (list): List of forecasts quantiles to compute in the forecasts_df
        include_history (bool): True to append to the forecasts dataframe the training data
        time_column_name (str): Time column name used in training
        identifiers_columns (list): List of timeseries identifiers column names used in training.
        forecasts_df (DataFrame): Dataframe with the different quantiles forecasts and the training data if include_history is True
    """

    def __init__(self, predictor, gluon_dataset, prediction_length, quantiles, include_history):
        self.predictor = predictor
        self.gluon_dataset = gluon_dataset
        self.prediction_length = predictor.prediction_length if prediction_length == -1 else prediction_length
        self.quantiles = quantiles
        self.include_history = include_history
        self.time_column_name = None
        self.identifiers_columns = None
        self.forecasts_df = None
        self._check()

    def predict(self):
        """
        Use the gluon dataset of training to predict future values and
        concat all forecasts timeseries of different identifiers and quantiles together
        """
        forecasts = self.predictor.predict(self.gluon_dataset)
        forecasts_list = list(forecasts)

        forecasts_timeseries = self._compute_forecasts_timeseries(forecasts_list)

        multiple_df = concat_timeseries_per_identifiers(forecasts_timeseries)

        self.forecasts_df = concat_all_timeseries(multiple_df)

        self.time_column_name = self.gluon_dataset.list_data[0][TIMESERIES_KEYS.TIME_COLUMN_NAME]
        self.identifiers_columns = (
            list(self.gluon_dataset.list_data[0][TIMESERIES_KEYS.IDENTIFIERS].keys()) if TIMESERIES_KEYS.IDENTIFIERS in self.gluon_dataset.list_data[0] else []
        )

        if self.include_history:
            frequency = forecasts_list[0].freq
            self.forecasts_df = self._include_history(frequency)

        self.forecasts_df = add_row_origin(self.forecasts_df, both=ROW_ORIGIN.FORECAST, left_only=ROW_ORIGIN.HISTORY)

        self.forecasts_df = self.forecasts_df.rename(columns={"index": self.time_column_name})

    def _include_history(self, frequency):
        """Include the historical data on which the model was trained to the forecasts dataframe.

        Args:
            frequency (str): Used to reconstruct the date range (because a gluon ListDataset only store the start date).

        Returns:
            DataFrame containing both the historical data and the forecasted values.
        """
        history_timeseries = self._retrieve_history_timeseries(frequency)
        multiple_df = concat_timeseries_per_identifiers(history_timeseries)
        history_df = concat_all_timeseries(multiple_df)
        return history_df.merge(self.forecasts_df, on=["index"] + self.identifiers_columns, how="left", indicator=True)

    def _generate_history_target_series(self, timeseries, frequency):
        """Creates a pandas time series from the past target values with Nan values for the prediction_length future dates.

        Args:
            timeseries (dict): Univariate timeseries dictionary created with the GluonDataset class.
            frequency (str): Used in pandas.date_range.

        Returns:
            Series with DatetimeIndex.
        """
        target_series = pd.Series(
            np.append(timeseries[TIMESERIES_KEYS.TARGET], np.repeat(np.nan, self.prediction_length)),
            name=timeseries[TIMESERIES_KEYS.TARGET_NAME],
            index=pd.date_range(
                start=timeseries[TIMESERIES_KEYS.START],
                periods=len(timeseries[TIMESERIES_KEYS.TARGET]) + self.prediction_length,
                freq=frequency,
            ),
        )
        return target_series

    def _generate_history_external_features_dataframe(self, timeseries, frequency):
        """Creates a pandas time series from the past and future external features values.

        Args:
            timeseries (dict): Univariate timeseries dictionary created with the GluonDataset class.
            frequency (str): Used in pandas.date_range.

        Returns:
            DataFrame with DatetimeIndex.
        """
        external_features_df = pd.DataFrame(
            timeseries[TIMESERIES_KEYS.FEAT_DYNAMIC_REAL].T[: len(timeseries[TIMESERIES_KEYS.TARGET]) + self.prediction_length],
            columns=timeseries[TIMESERIES_KEYS.FEAT_DYNAMIC_REAL_COLUMNS_NAMES],
            index=pd.date_range(
                start=timeseries[TIMESERIES_KEYS.START],
                periods=len(timeseries[TIMESERIES_KEYS.TARGET]) + self.prediction_length,
                freq=frequency,
            ),
        )
        return external_features_df

    def _retrieve_history_timeseries(self, frequency):
        """Reconstruct the history timeseries from the gluon_dataset object and fill the dates to predict with Nan values.

        Args:
            frequency (str)

        Returns:
            Dictionary of list of timeseries by identifiers (None if no identifiers)
        """
        history_timeseries = {}
        for i, timeseries in enumerate(self.gluon_dataset.list_data):
            if TIMESERIES_KEYS.IDENTIFIERS in timeseries:
                timeseries_identifier_key = tuple(sorted(timeseries[TIMESERIES_KEYS.IDENTIFIERS].items()))
            else:
                timeseries_identifier_key = None

            target_series = self._generate_history_target_series(timeseries, frequency)

            if TIMESERIES_KEYS.FEAT_DYNAMIC_REAL_COLUMNS_NAMES in timeseries:
                assert timeseries[TIMESERIES_KEYS.FEAT_DYNAMIC_REAL].shape[1] >= len(timeseries[TIMESERIES_KEYS.TARGET]) + self.prediction_length
                if timeseries_identifier_key not in history_timeseries:
                    external_features_df = self._generate_history_external_features_dataframe(timeseries, frequency)
                    history_timeseries[timeseries_identifier_key] = [external_features_df]

            if timeseries_identifier_key in history_timeseries:
                history_timeseries[timeseries_identifier_key] += [target_series]
            else:
                history_timeseries[timeseries_identifier_key] = [target_series]
        return history_timeseries

    def _compute_forecasts_timeseries(self, forecasts_list):
        """Compute all forecasts timeseries for each quantile.

        Args:
            forecasts_list (list): List of gluonts.model.forecast.Forecast (objects storing the predicted distributions as samples).

        Returns:
            Dictionary of list of forecasts timeseries by identifiers (None if no identifiers)
        """
        forecasts_timeseries = {}
        for i, sample_forecasts in enumerate(forecasts_list):
            if TIMESERIES_KEYS.IDENTIFIERS in self.gluon_dataset.list_data[i]:
                timeseries_identifier_key = tuple(sorted(self.gluon_dataset.list_data[i][TIMESERIES_KEYS.IDENTIFIERS].items()))
            else:
                timeseries_identifier_key = None

            if i == 0 and isinstance(sample_forecasts, QuantileForecast):
                self.quantiles = self._round_to_existing_quantiles(sample_forecasts)

            for quantile in self.quantiles:
                forecasts_label_prefix = "forecast"
                if quantile < 0.5:
                    forecasts_label_prefix += "_lower"
                elif quantile > 0.5:
                    forecasts_label_prefix += "_upper"

                forecasts_series = (
                    sample_forecasts.quantile_ts(quantile)
                    .rename(f"{forecasts_label_prefix}_{self.gluon_dataset.list_data[i][TIMESERIES_KEYS.TARGET_NAME]}")
                    .iloc[: self.prediction_length]
                )
                if timeseries_identifier_key in forecasts_timeseries:
                    forecasts_timeseries[timeseries_identifier_key] += [forecasts_series]
                else:
                    forecasts_timeseries[timeseries_identifier_key] = [forecasts_series]
        return forecasts_timeseries

    def _reorder_forecasts_df(self):
        """ Reorder columns with timeseries identifiers columns right after time column """
        forecasts_columns = [column for column in self.forecasts_df if column not in [self.time_column_name] + self.identifiers_columns]
        self.forecasts_df = self.forecasts_df[[self.time_column_name] + self.identifiers_columns + forecasts_columns]

    def get_forecasts_df(self, session=None, model_label=None):
        """Add the session timestamp and model label to the forecasts dataframe. Sort timeseries in revert order to display predictions on top.

        Args:
            session (Timstamp, optional)
            model_label (str, optional)

        Returns:
            Forecasts DaaFrame
        """
        if TIMESERIES_KEYS.IDENTIFIERS in self.gluon_dataset.list_data[0]:
            self._reorder_forecasts_df()
        if session:
            self.forecasts_df[METRICS_DATASET.SESSION] = session
        if model_label:
            self.forecasts_df[METRICS_DATASET.MODEL_COLUMN] = model_label

        self.forecasts_df = self.forecasts_df.sort_values(
            by=self.identifiers_columns + [self.time_column_name], ascending=[True] * len(self.identifiers_columns) + [False]
        )

        return self.forecasts_df

    def create_forecasts_column_description(self):
        """ Explain the meaning of the forecasts columns """
        column_descriptions = METRICS_COLUMNS_DESCRIPTIONS
        confidence_interval = self._retrieve_confidence_interval()
        for column in self.forecasts_df.columns:
            if "forecast_lower_" in column:
                column_descriptions[column] = f"Lower bound of the {confidence_interval}% forecasts confidence interval."
            elif "forecast_upper_" in column:
                column_descriptions[column] = f"Upper bound of the {confidence_interval}% forecasts confidence interval."
            elif "forecast_" in column:
                column_descriptions[column] = "Median of probabilistic forecasts"
        return column_descriptions

    def _check(self):
        """ Raises ValueError if the selected prediction_length is higher than the one used in training """
        if self.predictor.prediction_length < self.prediction_length:
            raise ValueError(f"Please choose a forecasting horizon lower or equal to the one chosen when training: {self.predictor.prediction_length}")

    def _round_to_existing_quantiles(self, sample_forecasts):
        """Find the quantiles that exists in sample_forecasts that are closest to the selected quantiles.
        QuantileForecast cannot predict all quantiles but only a list predifined during training.

        Args:
            sample_forecasts (QuantileForecast)

        Returns:
            List of quantiles that exists in the sample_forecasts
        """
        new_quantiles = []
        possible_quantiles = list(map(float, sample_forecasts.forecast_keys))
        for quantile in self.quantiles:
            new_quantiles += [min(possible_quantiles, key=lambda x: abs(x - quantile))]
        return new_quantiles

    def _retrieve_confidence_interval(self):
        """Retrieve the confidence interval percentage from the minimum and maximum quantiles.
        If they are not symetric around 0.5, log a warning.

        Returns:
            Integer representing the percentage of the confidence interval.
        """
        lower_quantile, upper_quantile = min(self.quantiles), max(self.quantiles)
        confidence_interval = round((upper_quantile - lower_quantile) * 100)
        if round((1 - upper_quantile) * 100, 2) != round(lower_quantile * 100, 2):
            logger.warning(
                f"The output confidence interval is not centered around the median. Lower and upper quantiles are [{lower_quantile}, {upper_quantile}]"
            )
        return confidence_interval
