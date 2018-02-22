import enchant
import logging as log
import numpy as np

from sklearn.feature_extraction.text import CountVectorizer

class SmartTagger(object):
    def __init__(self, weights={'description': 4, 'id': 6, 'tags': 2}):
        self._english = enchant.Dict('en_US')
        self.weights = weights
    
    def _is_hack_word(self, term):
        return not self._english.check(term)
    
    def _enrich_tags(self, row):
        tags = row['tags']
        if tags:
            tag_weights = {tag.lower(): self.weights['tags'] * self.idfs_[tag.lower()] for tag in tags.split(',') if tag}
        else:
            tag_weights = {}

        for feature in 'description', 'id':
            weight = self.weights[feature]
            tag_counts = self._cv.transform([row[feature]])
            for index in tag_counts.nonzero()[1]:
                term = self._cv_vocab[index]
                idf = self.idfs_[term]
                tag_weights[term] = tag_weights.get(term, 0) + weight * idf

        etags = [f'{pair[0]} {pair[1]}' for pair in sorted(tag_weights.items())]
        rowcopy = row.copy()
        rowcopy['etags'] = ','.join(etags)
        #log.debug("Original tags: %s", tags)
        #log.debug("Enriched tags: %s", etags)
        return rowcopy

    def fit_transform(self, df):
        self.tags_vocab_ = set([tag.lower() for tags in df['tags'] for tag in tags.split(',') if tag])
        self.idfs_ = self._compute_idfs(df)

        self._cv_vocab = list(filter(self._is_hack_word, self.tags_vocab_))
        self._cv = CountVectorizer(vocabulary=self._cv_vocab)

        return df.apply(self._enrich_tags, axis=1)

    def _compute_idfs(self, df):
        # IDF (inverse document frequency) formula: log N / n_t
        # N is the number of documents (aka packages)
        # n_t is the number of documents tagged with term t
        N = df.shape[0]
        nts = {tag: 0 for tag in self.tags_vocab_}
        for index, row in df.iterrows():
            seen = {}
            for tag in  row['tags'].split(','):
                tag = tag.lower()
                if tag and not seen.get(tag, False):
                    nts[tag] += 1
                    seen[tag] = True

        log10_N = np.log10(N)
        return {tag: log10_N - np.log10(nt) for tag, nt in nts.items()}
