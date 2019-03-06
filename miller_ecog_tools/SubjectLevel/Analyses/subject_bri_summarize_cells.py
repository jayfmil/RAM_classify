"""

"""
import os
import pycircstat
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray

from collections import Counter
from tqdm import tqdm
from joblib import Parallel, delayed
from scipy import signal
from scipy.stats import zscore, ttest_ind, sem
from scipy.signal import hilbert
from ptsa.data.timeseries import TimeSeries
from ptsa.data.filters import MorletWaveletFilter
from mpl_toolkits.axes_grid1 import make_axes_locatable

from miller_ecog_tools.SubjectLevel.subject_analysis import SubjectAnalysisBase
from miller_ecog_tools.SubjectLevel.subject_BRI_data import SubjectBRIData
from miller_ecog_tools.Utils import neurtex_bri_helpers as bri

# figure out the number of cores available for a parallel pool. Will use half
import multiprocessing
NUM_CORES = multiprocessing.cpu_count()


class SubjectBRISummarizeCellsAnalysis(SubjectAnalysisBase, SubjectBRIData):
    """
    Summarize the firing patterns for a given cell.

    Does it fire more for novel or repeated items?
    Does it fire more for specific stimuli?
    Does any firing patterns persist over time?

    """

    def __init__(self, task=None, subject=None, montage=0):
        super(SubjectBRISummarizeCellsAnalysis, self).__init__(task=task, subject=subject, montage=montage)

        # this needs to be an event-locked analyses
        self.do_event_locked = True

        # intervals to compute spiking statistics
        self.baseline_interval = [-1., 0]
        self.item_interval = [0, 1.5]

        # intervals to compute binned spiking statistics
        self.binned_intervals = [[0., .25],
                                 [.25, .5],
                                 [.5, .75],
                                 [.75, 1.],
                                 [1., 1.25],
                                 [1.25, 1.5]]

        # settings for guassian kernel used to smooth spike trains
        # enter .kern_width in milliseconds
        self.kern_width = 200
        self.kern_sd = 20

        # string to use when saving results files
        self.res_str = 'spike_activation.p'

    def _generate_res_save_path(self):
        self.res_save_dir = os.path.join(os.path.split(self.save_dir)[0], self.__class__.__name__+'_res')

    def analysis(self):
        """
        For each session, channel
        """

        if self.subject_data is None:
            print('%s: compute or load data first with .load_data()!' % self.subject)

        # open a parallel pool using joblib
        # with Parallel(n_jobs=int(NUM_CORES/2) if NUM_CORES != 1 else 1,  verbose=5) as parallel:

        # loop over sessions
        for session_name, session_grp in self.subject_data.items():
            print('{} processing.'.format(session_grp.name))

            # and channels
            for channel_num, channel_grp in tqdm(session_grp.items()):
                self.res[channel_grp.name] = {}
                self.res[channel_grp.name]['firing_rates'] = {}

                # load behavioral events
                events = pd.read_hdf(self.subject_data.filename, channel_grp.name + '/event')
                events['item_name'] = events.name.apply(lambda x: x.split('_')[1])

                # load eeg for this channel.
                eeg_channel = self._create_eeg_timeseries(channel_grp, events)

                # length of buffer in samples. Used below for extracting smoothed spikes
                samples = int(np.ceil(float(eeg_channel['samplerate']) * self.buffer))

                # also store region and hemisphere for easy reference. and time
                self.res[channel_grp.name]['region'] = eeg_channel.event.data['region'][0]
                self.res[channel_grp.name]['hemi'] = eeg_channel.event.data['hemi'][0]

                # for each cluster in the channel, summarize the spike activity
                for cluster_num, cluster_grp in channel_grp['spike_times'].items():
                    clust_str = cluster_grp.name.split('/')[-1]

                    # first compute number of spikes at each timepoint and the time in samples when each occurred
                    spike_counts, spike_rel_times = self._create_spiking_counts(cluster_grp, events,
                                                                                eeg_channel.shape[1])

                    # based on the spiking, compute firing rate and normalized firing rate for the default
                    # presentation interval
                    firing_df = self._make_firing_df(eeg_channel, spike_counts, events)

                    # also smooth firing rate and compute the above info for binned chunks of time
                    kern_width_samples = int(eeg_channel.samplerate.data / (1000/self.kern_width))
                    kern = signal.gaussian(kern_width_samples, self.kern_sd)
                    kern /= kern.sum()
                    smoothed_spike_counts = np.stack([signal.convolve(x, kern, mode='same')
                                                      for x in spike_counts], 0)

                    # now compute the firing rate data for the binned intervals
                    df_binned = []
                    for this_bin in self.binned_intervals:
                        this_df = self._make_firing_df(eeg_channel.time.data, smoothed_spike_counts, events,
                                                       item_interval=this_bin)
                        this_df = pd.concat([this_df], keys=['{}-{}'.format(*this_bin)])
                        df_binned.append(this_df)
                    df_binned = pd.concat(df_binned, axis=0)

                    self.res[channel_grp.name]['firing_rates'][clust_str] = {}
                    self.res[channel_grp.name]['firing_rates'][clust_str]['paired_firing_df'] = firing_df
                    self.res[channel_grp.name]['firing_rates'][clust_str]['binned_paired_firing_df'] = df_binned

    def _make_firing_df(self, time_ax, spiking_array, events, baseline_interval=None, item_interval=None):

        if baseline_interval is None:
            baseline_interval = self.baseline_interval
        if item_interval is None:
            item_interval = self.item_interval

        # normalize the presentation interval based on the mean and standard deviation of a pre-stim interval
        baseline_bool = (time_ax >= baseline_interval[0]) & (time_ax <= baseline_interval[1])
        baseline_spiking = np.sum(spiking_array[:, baseline_bool], axis=1) / np.ptp(baseline_interval)
        baseline_mean = np.mean(baseline_spiking)
        baseline_std = np.std(baseline_spiking)

        # get the firing rate of the presentation interval now and zscore it
        presentation_bool = (time_ax >= item_interval[0]) & (time_ax <= item_interval[1])
        presentation_spiking = np.sum(spiking_array[:, presentation_bool], axis=1) / np.ptp(item_interval)
        z_firing = (presentation_spiking - baseline_mean) * baseline_std

        # filter to just items that have pairings
        paired = np.array([np.sum(events.item_name.values == x) for x in events.item_name.values]) == 2
        presentation_spiking = presentation_spiking[paired]
        z_firing = z_firing[paired]
        item_names = events['item_name'].values[paired]
        is_first = events['isFirst'].values[paired]

        # sort by items
        sort_order = np.argsort(item_names)
        presentation_spiking = presentation_spiking[sort_order]
        z_firing = z_firing[sort_order]
        item_names = item_names[sort_order]
        is_first = is_first[sort_order]

        # make dataframe
        index = [item_names, is_first]
        data = [presentation_spiking, z_firing]
        df = pd.DataFrame(data=np.stack(data, -1), index=index, columns=['firing_rate', 'z_firing_rate'])
        return df

    def _create_spiking_counts(self, cluster_grp, events, n):
        spike_counts = []
        spike_ts = []

        # loop over each event
        for index, e in events.iterrows():
            # load the spike times for this cluster
            spike_times = np.array(cluster_grp[str(index)])

            # interpolate the timestamps for this event
            start = e.stTime + self.start_ms * 1000
            stop = e.stTime + self.stop_ms * 1000
            timestamps = np.linspace(start, stop, n, endpoint=True)

            # find the closest timestamp to each spike (technically, the closest timestamp following a spike, but I
            # think this level of accuracy is fine). This is the searchsorted command. Then count the number of spikes
            # that occurred at each timepoint with histogram
            spike_bins = np.searchsorted(timestamps, spike_times)
            bin_counts, _ = np.histogram(spike_bins, np.arange(len(timestamps) + 1))
            spike_counts.append(bin_counts)
            spike_ts.append(spike_bins)

        return np.stack(spike_counts, 0), spike_ts

    def _create_eeg_timeseries(self, grp, events):
        data = np.array(grp['ev_eeg'])
        time = grp.attrs['time']
        channel = grp.attrs['channel']
        sr = grp.attrs['samplerate']

        # create an TimeSeries object (in order to make use of their wavelet calculation)
        dims = ('event', 'time', 'channel')
        coords = {'event': events[events.columns[events.columns != 'index']].to_records(),
                  'time': time,
                  'channel': [channel]}

        return TimeSeries.create(data, samplerate=sr, dims=dims, coords=coords)

    def _create_spike_timeseries(self, spike_data, time, sr, events):
        # create an TimeSeries object
        dims = ('event', 'time')
        coords = {'event': events[events.columns[events.columns != 'index']].to_records(),
                  'time': time}
        return TimeSeries.create(spike_data, samplerate=sr, dims=dims, coords=coords)

































