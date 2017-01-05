from GroupLevel.group import Group
from operator import itemgetter
from itertools import groupby
from scipy.stats import ttest_1samp, sem

import pdb
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt


class GroupSpectralShift(Group):
    """
    Subclass of Group. Used to run subject_spectral_shift.
    """

    def __init__(self, analysis='spectral_shift_enc', subject_settings='default', open_pool=False, n_jobs=100,
                 **kwargs):
        super(GroupSpectralShift, self).__init__(analysis=analysis, subject_settings=subject_settings,
                                                 open_pool=open_pool, n_jobs=n_jobs, **kwargs)

    def process(self):
        """
        Call Group.process() to compute the subsequent memory effect for each subject.
        """
        super(GroupSpectralShift, self).process()

    def plot_tstat_sme(self, region=None):
        """
        Plots mean t-statistics, across subjects, comparing remembered and not remembered items as a function of
        frequency. Very similar to the same function in group_SME, but modified to because the last two elements in
        res['ts'] here are slope and offset.
        """

        regions = self.subject_objs[0].res['regions']

        # Use all electrodes if region is None. Mean within each subject.
        if region is None:
            ts = np.stack([x.res['ts'].mean(axis=1) for x in self.subject_objs], axis=0)
            region = 'All'
        else:

            # otherwise, just pull out the electrodes in the ROI. NB: These have already been averaged within subject.
            region_ind = regions == region
            if ~np.any(region_ind):
                print('Invalid region, please use: %s.' % ', '.join(regions))
                return
            ts = np.stack([x.res['ts_region'][:, region_ind].flatten() for x in self.subject_objs], axis=0)

        # t, p = ttest_1samp(ts, 0, axis=0, nan_policy='omit')

        # y values is the mean t-stat. Last two elements exlcuded because those are slope and offset
        y_mean = np.nanmean(ts, axis=0)[:-2]
        y_sem = sem(ts, axis=0, nan_policy='omit')[:-2] * 1.96
        x = np.log10(self.subject_objs[0].freqs)

        # also compute the mean slope and offsets
        pdb.set_trace()

        with plt.style.context('myplotstyle.mplstyle'):

            # plot with a shaded 95% CI
            fig, ax = plt.subplots()
            ax.plot(x, y_mean, '-k', linewidth=4, zorder=6)
            ax.fill_between(x, y_mean - y_sem, y_mean + y_sem, facecolor=[.5, .5, .5, .5], edgecolor=[.5, .5, .5, .5], zorder=5)
            ax.plot([x[0], x[-1]], [0, 0], '-k', linewidth=2)

            # relabel x-axis to be powers of two
            new_x = self.compute_pow_two_series()
            _ = plt.xticks(np.log10(new_x), new_x, rotation=0)
            plt.ylim(-1, 1)

            ax.set_xlabel('Frequency', fontsize=24)
            ax.set_ylabel('Average t-stat', fontsize=24)
            plt.title('%s SME, N=%d' % (region, np.sum(~np.isnan(ts), axis=0)[0]))

    def plot_count_sme(self, region=None):
        """

        """

        regions = self.subject_objs[0].res['regions']

        if region is None:
            sme_pos = np.stack([np.sum((x.res['ts'][:-2] > 0) & (x.res['ps'][:-2] < .05), axis=1) for x in self.subject_objs],
                               axis=0)
            sme_neg = np.stack([np.sum((x.res['ts'][:-2] < 0) & (x.res['ps'][:-2] < .05), axis=1) for x in self.subject_objs],
                               axis=0)
            n = np.stack([x.res['ts'].shape[1] for x in self.subject_objs], axis=0)
            region = 'All'
        else:
            region_ind = regions == region
            if ~np.any(region_ind):
                print('Invalid region, please use: %s.' % ', '.join(regions))
                return

            sme_pos = np.stack([x.res['sme_count_pos'][:-2, region_ind].flatten() for x in self.subject_objs], axis=0)
            sme_neg = np.stack([x.res['sme_count_neg'][:-2, region_ind].flatten() for x in self.subject_objs], axis=0)
            n = np.stack([x.res['elec_n'][region_ind].flatten() for x in self.subject_objs], axis=0)

        n = float(n.sum())
        x = np.log10(self.subject_objs[0].freqs)
        x_label = np.round(self.subject_objs[0].freqs * 10) / 10
        with plt.style.context('myplotstyle.mplstyle'):
            plt.plot(x, sme_pos.sum(axis=0) / n, linewidth=4, c='#8c564b', label='Good Memory')
            plt.plot(x, sme_neg.sum(axis=0) / n, linewidth=4, c='#1f77b4', label='Bad Memory')
            l = plt.legend(loc=0)
            plt.xticks(x[::3], x_label[::3], rotation=-45)
            plt.xlabel('Frequency', fontsize=24)
            plt.ylabel('Percent Sig. Electrodes', fontsize=24)
            plt.title('%s: %d electrodes' % (region, int(n)))

    def compute_pow_two_series(self):
        """
        This convoluted line computes a series powers of two up to and including one power higher than the
        frequencies used. Will use this as our x-axis ticks and labels so we can have nice round values.
        """
        return np.power(2, range(int(np.log2(2 ** (int(self.subject_objs[0].freqs[-1]) - 1).bit_length())) + 1))