
import pandas, numpy
from matplotlib import pyplot
from src.msfe import db_connector
from src.qcmg import metrics_generator
from src.constants import all_metrics
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from PyAstronomy import pyasl


def correct_outlier_prediction_for_metric(metric, prediction, metric_values):
    """ This method corrects outlier prediction of methods, that don't take into account the nature of the metric.
        E.g., predicted outliers with very high resolution are marked as normal values,
              predicted outliers with very low chemical_dirt are marked as normal values, as well. """

    prediction[prediction == -1] = 0  # reformat predictions to {0,1}

    if metric in ["resolution_200", "resolution_700", "signal", "s2b", "s2n"]:

        metric_values = metric_values.reshape(1, -1)[0]
        # only low values can be marked as outliers, while high values are ok
        values_higher_than_median = metric_values > numpy.median(metric_values)
        corrected_prediction = prediction + values_higher_than_median  # vectorized 'or' operator

    elif metric in ["average_accuracy", "chemical_dirt", "instrument_noise", "baseline_25_150", "baseline_50_150", "baseline_25_650", "baseline_50_650"]:

        metric_values = metric_values.reshape(1, -1)[0]
        # only high values can be marked as outliers, while low values are ok
        values_lower_than_median = metric_values < numpy.median(metric_values)
        corrected_prediction = prediction + values_lower_than_median  # vectorized 'or' operator
    else:
        # no correction is done for metrics:
        # "isotopic_presence", "transmission", "fragmentation_305", "fragmentation_712"
        return prediction

    return corrected_prediction


def compare_outlier_prediction_methods():
    """ This method evaluates outlier prediction for each QC metric using methods:
        - Isolation Forest (seems the best),
        - Local Outlier Factor,
        - Quantile-based (in-house),
        - Generalized ESD (Extreme Studentized Deviate).
        Minimal data preprocessing and plotting is done. """

    # qualities_data, _ = db_connector.fetch_table(conn, "qc_metrics_qualities")
    # qualities_data = pandas.DataFrame(qualities_data, columns=colnames)

    metrics_path = "/Users/andreidm/ETH/projects/monitoring_system/res/nas2/qc_metrics_database.sqlite"

    conn = db_connector.create_connection(metrics_path)
    metrics_data, colnames = db_connector.fetch_table(conn, "qc_metrics")

    # convert to dataframes for convenience
    metrics_data = pandas.DataFrame(metrics_data, columns=colnames)
    metrics_data = metrics_data.loc[metrics_data["acquisition_date"] < "2020-03-29", :]  # remove Mauro's dataset

    quality_table = metrics_generator.compute_quality_table_first_time(metrics_data)

    # pandas.set_option('display.max_rows', None)
    # pandas.set_option('display.max_columns', None)
    # print(quality_table)

    for metric_name in all_metrics:
        # reshape data to feed to models
        single_metric = numpy.array(metrics_data.loc[:, metric_name]).reshape(-1, 1)

        # detect outliers with isolation forest
        forest = IsolationForest(random_state=0)  # effectively, allows ~15% of outliers
        forest.fit(single_metric)
        forest_prediction = forest.predict(single_metric)
        forest_corrected_prediction = correct_outlier_prediction_for_metric(metric_name, forest_prediction, single_metric)

        # detect outliers with local outlier factor
        lof = LocalOutlierFactor()
        lof_prediction = lof.fit_predict(single_metric)
        lof_corrected_prediction = correct_outlier_prediction_for_metric(metric_name, lof_prediction, single_metric)

        # TODO: check correction carefully, there's something wrong with it

        # detect outliers with GESD
        gesd_prediction_indices = pyasl.generalizedESD(single_metric, int(single_metric.shape[0] * 0.2), 0.05)[1]
        gesd_prediction = numpy.ones(shape=(single_metric.shape[0]))  # make an empty ("all good") array
        gesd_prediction[gesd_prediction_indices] = 0  # add predicted outliers by indices
        gesd_corrected_prediction = correct_outlier_prediction_for_metric(metric_name, gesd_prediction, single_metric)

        # prepare data for plotting
        dates = metrics_data.loc[:, "acquisition_date"]
        dates_labels = numpy.array([str(date)[0:10] for date in metrics_data.loc[:, "acquisition_date"]])
        values = metrics_data.loc[:, metric_name]

        # plot
        fig, axs = pyplot.subplots(4, 1, sharex='col', figsize=(12, 8))

        # the strictest, non-adaptable
        axs[0].plot(dates, values, 'k-o')
        axs[0].plot(dates[quality_table[metric_name] == 0], values[quality_table[metric_name] == 0], 'r.')
        axs[0].title.set_text("quantile-based")
        axs[0].set_ylabel(metric_name)
        axs[0].grid()

        # less strict, adaptable -> optimal?
        axs[1].plot(dates, values, 'k-o')
        axs[1].plot(dates[forest_corrected_prediction == 0], values[forest_corrected_prediction == 0], 'r.')
        axs[1].title.set_text("isolation forest")
        axs[1].set_ylabel(metric_name)
        axs[1].grid()

        # more tolerant, adaptable
        axs[2].plot(dates, values, 'k-o')
        axs[2].plot(dates[lof_corrected_prediction == 0], values[lof_corrected_prediction == 0], 'r.')
        axs[2].title.set_text("local outlier factor")
        axs[2].set_ylabel(metric_name)
        axs[2].grid()

        # most tolerant, adaptable
        axs[3].plot(dates, values, 'k-o')
        axs[3].plot(dates[gesd_corrected_prediction == 0], values[gesd_corrected_prediction == 0], 'r.')
        axs[3].title.set_text("generalized ESD")
        axs[3].set_ylabel(metric_name)
        axs[3].grid()

        pyplot.xticks(dates[::2], dates_labels[::2], rotation='vertical')
        pyplot.tight_layout()
        pyplot.show()


if __name__ == "__main__":

    # TODO: test prediction of the next point, based on previous entries
    # qualities_data, _ = db_connector.fetch_table(conn, "qc_metrics_qualities")
    # qualities_data = pandas.DataFrame(qualities_data, columns=colnames)

    metrics_path = "/Users/andreidm/ETH/projects/monitoring_system/res/nas2/qc_metrics_database.sqlite"

    conn = db_connector.create_connection(metrics_path)
    metrics_data, colnames = db_connector.fetch_table(conn, "qc_metrics")

    # convert to dataframes for convenience
    metrics_data = pandas.DataFrame(metrics_data, columns=colnames)
    test_data = metrics_data.loc[metrics_data["acquisition_date"] >= "2020-04-19", :]
    metrics_data = metrics_data.loc[metrics_data["acquisition_date"] < "2020-04-19", :]

    quality_table = metrics_generator.compute_quality_table_first_time(metrics_data)

    for metric_name in all_metrics:
        # reshape data to feed to models
        single_metric = numpy.array(metrics_data.loc[:, metric_name]).reshape(-1, 1)
        test_metric = numpy.array(test_data.loc[:, metric_name]).reshape(-1, 1)

        # detect outliers with isolation forest
        forest = IsolationForest(random_state=0)  # effectively, allows ~15% of outliers
        forest.fit(single_metric)

        train_prediction = forest.predict(single_metric)
        train_corrected_prediction = correct_outlier_prediction_for_metric(metric_name, train_prediction, single_metric)

        test_prediction = forest.predict(test_metric)
        test_corrected_prediction = correct_outlier_prediction_for_metric(metric_name, test_prediction, single_metric)

        # prepare data for plotting
        dates = metrics_data.loc[:, "acquisition_date"]
        dates_labels = numpy.array([str(date)[0:10] for date in metrics_data.loc[:, "acquisition_date"]])
        values = metrics_data.loc[:, metric_name]

        test_dates = test_data.loc[:, "acquisition_date"]
        test_dates_labels = numpy.array([str(date)[0:10] for date in test_data.loc[:, "acquisition_date"]])
        test_values = test_data.loc[:, metric_name]

        # plot
        fig, axs = pyplot.subplots(1, 2, sharey=True, figsize=(12,6))

        pyplot.setp(axs, xticks=[], xticklabels=[])

        axs[0].plot(dates, values, 'k-o')
        axs[0].plot(dates[train_corrected_prediction == 0], values[train_corrected_prediction == 0], 'y.')
        axs[0].title.set_text("training")
        axs[0].set_ylabel(metric_name)
        axs[0].grid()

        axs[1].plot(test_dates, test_values, 'k-o')
        axs[1].plot(test_dates[test_corrected_prediction == 0], test_values[test_corrected_prediction == 0], 'r.')
        axs[1].title.set_text("test")
        axs[1].set_ylabel(metric_name)
        axs[1].grid()

        pyplot.sca(axs[0])
        pyplot.xticks(dates[::3], dates_labels[::3], rotation='vertical')
        pyplot.sca(axs[1])
        pyplot.xticks(test_dates, test_dates_labels, rotation='vertical')

        pyplot.tight_layout()
        pyplot.show()

