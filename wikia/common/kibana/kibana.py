"""
Run queries against Kibana's elasticsearch
@see http://elasticsearch-py.readthedocs.org/en/master/
"""
import json
import logging
import time

from datetime import datetime
from dateutil import tz

from elasticsearch import Elasticsearch

import config


class KibanaError(Exception):
    pass


class Kibana(object):
    # give 5 seconds for all log messages to reach logstash and be stored in elasticsearch
    SHORT_DELAY = 5

    # seconds in 24h used to get the es index for yesterday
    DAY = 86400

    """ Interface for querying Kibana's storage """
    def __init__(self, since=None, period=900):
        """
         :arg since: UNIX timestamp data should be fetched since
         :arg period: period (in seconds) before now() to be used when since is empty (defaults to last 15 minutes)
        """
        self._es = Elasticsearch(hosts=config.ELASTICSEARCH_HOSTS)
        self._logger = logging.getLogger('kibana')

        # if no timestamp provided, fallback to now() in UTC
        now = int(time.time())

        if since is None:
            since = now - period
        else:
            since += 1
            self._logger.info("Using provided {:d} timestamp as since ({:d} seconds ago)".format(since, now - since))

        self._since = since
        self._to = now - self.SHORT_DELAY  # give logs some time to reach Logstash

        # Elasticsearch index to query
        # from today and yesterday
        self._index = ','.join([
            self.format_index(now-self.DAY),
            self.format_index(now),
        ])

        self._logger.info("Using {} indices".format(self._index))
        self._logger.info("Querying for messages from between {} and {}".
                          format(self.format_timestamp(self._since), self.format_timestamp(self._to)))

    @staticmethod
    def format_index(ts):
        # ex. logstash-2014.07.08
        tz_info = tz.tzutc()
        return "logstash-%s" % datetime.fromtimestamp(ts, tz=tz_info).strftime('%Y.%m.%d')

    @staticmethod
    def format_timestamp(ts):
        """
        Format the UTC timestamp for Elasticsearch
        eg. 2014-07-09T08:37:18.000Z

        @see https://docs.python.org/2/library/time.html#time.strftime
        """
        tz_info = tz.tzutc()
        return datetime.fromtimestamp(timestamp=ts, tz=tz_info).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _get_timestamp_filer(self):
        return {
            "range": {
                "@timestamp": {
                    "from": self.format_timestamp(self._since),
                    "to": self.format_timestamp(self._to)
                }
            }
        }

    def _search(self, body, limit=0):
        """
        Perform the search and return raw rows

        :arg body: query JSON body
        :arg limit: how many rows to return
        :return: raw rows
        """
        body.setdefault("filter", self._get_timestamp_filer())
        body.setdefault("size", limit)

        self._logger.debug("Running {} query (limit set to {:d})".format(json.dumps(body), body.get('size', 0)))

        data = self._es.search(
            index=self._index,
            body=body,
        )

        if data['timed_out'] is True:
            raise KibanaError("The query timed out!")

        rows = [entry['_source'] for entry in data['hits']['hits']]

        self._logger.info("{:d} rows returned in {:d} ms".format(len(rows), data['took']))
        return rows

    def get_rows(self, match, limit=10):
        """
        Returns raw rows that matches given query

        :arg match: query to be run against Kibana log messages (ex. {"@message": "Foo Bar DB queries"})
        :arg limit: the number of results (defaults to 10)
        """
        body = {
            "query": {
                "match": match,
            }
        }

        return self._search(body, limit)

    def query_by_string(self, query, limit=10):
        """
        Returns raw rows that matches the given query string

        :arg query: query string to be run against Kibana log messages (ex. @message:"^PHP Fatal").
        :arg limit: the number of results (defaults to 10)
        """
        body = {
            "query": {
                "query_string": {
                    "query": query,
                }
            }
        }

        return self._search(body, limit)

    def get_to_timestamp(self):
        """ Return the upper time boundary to returned data """
        return self._to
