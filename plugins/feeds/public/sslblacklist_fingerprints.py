from io import StringIO
import logging
from datetime import timedelta, datetime

import pandas as pd

from core.schemas import observable
from core.schemas import task
from core import taskmanager

TYPE_DICT = {
    "MITM": ["mitm"],
    "C&C": ["c2"],
    "distribution": ["payload_delivery"],
    "sinkhole": ["sinkhole"],
}


class SSLBlackListCerts(task.FeedTask):
    _defaults = {
        "frequency": timedelta(hours=1),
        "name": "SSLBlackListCerts",
        "description": "SSLBlackListCerts is a community feed of SSL fingerprints which are updated every 24 hours.",
    }

    SOURCE = "https://sslbl.abuse.ch/blacklist/sslblacklist.csv"

    def run(self):
        response = self._make_request(self.SOURCE, verify=True)
        if response:
            data = response.text
            names=["Listingdate", "SHA1", "Listingreason"]
            df = pd.read_csv(
                StringIO(data),
                comment="#",
                delimiter=",",
                names=names,
                quotechar='"',
                quoting=True,
                skipinitialspace=True,
                parse_dates=["Listingdate"],
                header=8,
            )
            df.fillna("", inplace=True)
            df = self._filter_observables_by_time(df, "Listingdate")

            for _, line in df.iterrows():
                self.analyze(line)

    def analyze(self, line):
        first_seen = line["Listingdate"]
        _sha1 = line["SHA1"]
        reason = line["Listingreason"]

        tags = []
        tag = reason.split(" ")
        if len(tag) >= 2:
            family = tag[0]
            tags.append(family.lower())
        _type = tag[-1]

        if TYPE_DICT.get(_type):
            tags += TYPE_DICT[_type]

        tags.append("ssl_fingerprint")

        context_hash = {
            "source": self.name,
            "first_seen": first_seen,
        }

        cert_obs = observable.Observable.find(value=f"CERT:{_sha1}")
        if not cert_obs:
            cert_obs = observable.Observable(value=f"CERT:{_sha1}", type="certificate").save()
        

        cert_obs.add_context(self.name, context_hash)
        cert_obs.tag(tags)

        sha1_obs = observable.Observable.find(value=_sha1)
        if not sha1_obs:
            sha1_obs = observable.Observable(value=_sha1, type="sha1").save()

        sha1_obs.add_context(self.name, context_hash)
        sha1_obs.tag(tags)

        cert_obs.link_to(sha1_obs, "cert_sha1", self.name)

taskmanager.TaskManager.register_task(SSLBlackListCerts)
