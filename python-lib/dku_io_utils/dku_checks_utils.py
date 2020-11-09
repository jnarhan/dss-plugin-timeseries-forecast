import pandas as pd


def assert_continuous_time_column(dataframe, time_column_name, time_granularity_unit, time_granularity_step):
    """ raise an explicit error message """
    is_continuous = check_continuous_time_column(dataframe, time_column_name, time_granularity_unit, time_granularity_step)
    if not is_continuous:
        frequency = "{}{}".format(time_granularity_step, time_granularity_unit)
        error_message = "Time column {} doesn't have regular time intervals of frequency {}.".format(time_column_name, frequency)
        if time_granularity_unit in ['M', 'Y']:
            unit_name = 'Month' if time_granularity_step == 'M' else 'Year'
            error_message += "For {0} frequency, timestamps must be end of {0} (for e.g. '2020-12-31 00:00:00')".format(unit_name)
        raise ValueError(error_message)


def check_continuous_time_column(dataframe, time_column_name, time_granularity_unit, time_granularity_step):
    """ check that all timesteps are identical and follow the chosen frequency """
    dataframe[time_column_name] = pd.to_datetime(dataframe[time_column_name]).dt.tz_localize(tz=None)
    frequency = "{}{}".format(time_granularity_step, time_granularity_unit)

    start_date = dataframe[time_column_name].iloc[0]
    end_date = dataframe[time_column_name].iloc[-1]

    date_range_df = pd.date_range(start=start_date, end=end_date, freq=frequency).to_frame(index=False)

    if len(date_range_df.index) != len(dataframe.index) or not dataframe[time_column_name].equals(date_range_df[0]):
        return False
    return True


def external_features_future_dataset_schema_check(train_data_sample, external_features_future_dataset):
    """
    check that schema of external_features_future_dataset contains exactly and only
    time_column_name | feat_dynamic_real_columns_names | identifiers.keys()
    """
    external_features_future_columns = [column['name'] for column in external_features_future_dataset.read_schema()]
    expected_columns = [train_data_sample['time_column_name']] + train_data_sample['feat_dynamic_real_columns_names']
    if 'identifiers' in train_data_sample:
        expected_columns += list(train_data_sample['identifiers'].keys())
    if set(external_features_future_columns) != set(expected_columns):
        raise ValueError("The dataset of future values of external features must contains exactly the following columns: {}".format(expected_columns))


def external_features_check(gluon_train_dataset, external_features_future_dataset):
    """
    check that an external features dataset has been provided if and only external features were used during training
    return True if external features are needed for prediction
    """
    train_data_sample = gluon_train_dataset.list_data[0]
    trained_with_external_features = bool('feat_dynamic_real_columns_names' in train_data_sample)
    if trained_with_external_features and external_features_future_dataset:
        external_features_future_dataset_schema_check(train_data_sample, external_features_future_dataset)
        return True
    elif trained_with_external_features and not external_features_future_dataset:
        raise ValueError("You must provide a dataset of future values of external features.")
    elif not trained_with_external_features and external_features_future_dataset:
        raise ValueError("""
            A dataset of future values of external features was provided, but no external features were used during training for the selected model.
            Remove this dataset from the recipe inputs or select a model that used external features during training.
        """)
    return False
