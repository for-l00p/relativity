#!/usr/bin/env python3

import asyncio
import logging
import math
import numpy as np
import os
import sys

from argparse import ArgumentParser
from datetime import datetime

from blobber import gen_blobs
from data_prep import load_packages
from ml import FeatureTransformer, Recommender
from nuget_api import check_endpoint, PROD
from utils.logging import StyleAdapter

LOG = StyleAdapter(logging.getLogger(__name__))

def parse_args():
    parser = ArgumentParser()
    parser.add_argument(
        '-b', '--generate-blobs',
        help="generate json blobs",
        action='store_true',
        dest='generate_blobs'
    )
    parser.add_argument(
        '-c', '--chunk-size',
        metavar='SIZE',
        help="set number of catalog pages per training batch",
        action='store',
        dest='pages_per_chunk',
        type=int,
        default=100
    )
    parser.add_argument(
        '-d', '--debug',
        help="print debug information",
        action='store_const',
        dest='log_level',
        const=logging.DEBUG,
        default=logging.WARNING
    )
    parser.add_argument(
        '-e', '--endpoint',
        metavar='ENDPOINT',
        help="specify nuget api endpoint (DEV|INT|PROD, default PROD)",
        action='store',
        dest='api_endpoint',
        default=PROD
    )
    parser.add_argument(
        '--force-refresh-blobs',
        help="generate blobs for page X even if the corresponding directory already exists",
        action='store_true',
        dest='force_refresh_blobs'
    )
    parser.add_argument(
        '--force-refresh-packages',
        help="fetch packages for page X even if pageX.csv already exists",
        action='store_true',
        dest='force_refresh_packages'
    )
    parser.add_argument(
        '--force-refresh-vectors',
        help="always compute vectors during blob generation. use in conjunction with -b",
        action='store_true',
        dest='force_refresh_vectors'
    )
    parser.add_argument(
        '--include-weights',
        help="when used with --tag-dump, includes tag weights in output file",
        action='store_true',
        dest='include_weights'
    )
    parser.add_argument(
        '-l', '--page-limit',
        metavar='LIMIT',
        help="limit the number of pages loaded. 0 means load all pages. " \
             "if used in conjunction with -r, limit the number of pages downloaded from the catalog. " \
             "0 means download all pages.",
        action='store',
        dest='page_limit',
        type=int,
        default=0
    )
    parser.add_argument(
        '-r', '--refresh-packages',
        help="refresh package database",
        action='store_true',
        dest='refresh_packages'
    )
    parser.add_argument(
        '--reuse-vectors',
        help="during blob generation, assume vector files are present and skip feature transformation. " \
             "use in conjunction with -b.",
        action='store_true',
        dest='reuse_vectors'
    )
    parser.add_argument(
        '-s', '--page-start',
        metavar='START',
        help="start loading from page START. " \
             "if used in conjunction with -r, start downloading from page START.",
        action='store',
        dest='page_start',
        type=int,
        default=0
    )
    parser.add_argument(
        '-t', '--tag-dump',
        metavar='FILE',
        help="dump enriched tags to FILE (default: etags.log)",
        action='store',
        dest='etags_fname',
        nargs='?',
        const='etags.log'
    )
    return parser.parse_args()

# Print package ids and their recommendations, sorted by popularity
def print_recs(df, recs):
    MAX_FLOAT64 = np.finfo(np.float64).max

    pairs = list(recs.items())

    # This is necessary so we don't run through the dataframe every time sort calls
    # the key function, which would result in quadratic running time
    index_map = {}
    for index, row in enumerate(df.itertuples()):
        index_map[row.id] = index

    def sortkey(pair):
        id_ = pair[0]
        # NB: Python sorts tuples lexicographically (by 1st element, then by 2nd element, etc.)
        by, thenby = -df['downloads_per_day'][index_map[id_]], id_.lower()
        if math.isnan(by): # nan screws with sorting. Place nan entries last.
            by = MAX_FLOAT64
        return by, thenby

    pairs.sort(key=sortkey)
    lines = ["{}: {}".format(*pair) for pair in pairs]
    output = '\n'.join(lines)
    # print() can't handle certain characters because it uses the console's encoding.
    sys.stdout.buffer.write(output.encode('utf-8'))

async def main():
    def get_paths(endpoint):
        blobs_root = os.path.join('.', endpoint, 'blobs')
        packages_root = os.path.join('.', endpoint, 'packages')
        vectors_root = os.path.join('.', endpoint, 'vectors')
        return blobs_root, packages_root, vectors_root

    args = parse_args()
    logging.basicConfig(level=args.log_level)

    endpoint = check_endpoint(args.api_endpoint)
    blobs_root, packages_root, vectors_root = get_paths(endpoint)

    df, tagger = await load_packages(packages_root, args)

    if args.generate_blobs:
        gen_blobs(df,
                  tagger,
                  args,
                  blobs_root=blobs_root,
                  vectors_root=vectors_root)
    else:
        trans = FeatureTransformer(tags_vocab=tagger.vocab_)
        feats = trans.fit_transform(df)

        magic = Recommender(n_recs=5)
        magic.fit(feats, df, feats, df)
        recs = magic.predict(feats, df)

        print_recs(df, recs)

if __name__ == '__main__':
    start = datetime.now()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    end = datetime.now()
    seconds = (end - start).seconds
    print("Finished generating recommendations in {}s".format(seconds), file=sys.stderr)
