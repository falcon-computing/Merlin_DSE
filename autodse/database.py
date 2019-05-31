"""
The module of result database.
"""
import os
import pickle
from queue import PriorityQueue
from threading import Lock
from time import time
from typing import Any, List, Optional, Set, Tuple, Union

from .logger import get_default_logger
from .result import HLSResult, MerlinResult, Result


class Database():
    """The base class of result database with API definitions"""

    def __init__(self, name: str, cache_size: int = 1, db_file_path: Optional[str] = None):
        self.db_id = '{0}-{1}'.format(name, int(time()))
        self.log = get_default_logger('Database')

        # Set the database name to default if not specified
        if db_file_path is None:
            self.db_file_path = '{0}/{1}.db'.format(os.getcwd(), name)
            self.log.warning('No file name was given for dumping the database, dumping to %s',
                             self.db_file_path)
        else:
            self.db_file_path = db_file_path

        # Current best result set (min heap)
        # Note: the element type in this PriorityQueue is (quality, timestamp, result).
        # The purpose of using timestamp is to deal with points with same qualities,
        # since PriorityQueue tries to compare the second tuple value if the first one
        # is the same. We define the first point among the same quality points is
        # the one we want.
        # FIXME: we now rely on the main flow to control the size in order to
        # avoid race condition.
        self.best_cache_size = cache_size
        self.best_cache: PriorityQueue = PriorityQueue()

        # Code hash set
        # The purpose of the set is to avoid taking two points that result in the same
        # HLS code generated by Merlin.
        self.code_hash_set: Set[str] = set()

    def init_best_cache(self) -> None:
        """Initialize the best cache using the loaded data"""

        if self.count() == 0:
            return

        for result in [r for r in self.query_all() if isinstance(r, HLSResult) if r.valid]:
            self.best_cache.put((result.quality, time(), result), timeout=0.1)

    def init_code_hash_set(self) -> None:
        """Initialize the code hash set using the loaded data"""

        if self.count() == 0:
            return

        for result in [r for r in self.query_all() if isinstance(r, MerlinResult)]:
            if result.code_hash is not None:
                self.code_hash_set.add(result.code_hash)

    def add_code_hash(self, code_hash: str) -> bool:
        """Add a new code has to the set and check if it already exists.

        Parameters
        ----------
        code_hash:
            The code hash to be added.

        Returns
        -------
        bool:
            True if the given code hash is a new one; False if it alreay exists
        """

        if code_hash in self.code_hash_set:
            return False
        self.code_hash_set.add(code_hash)
        return True

    def update_best(self, result: Result) -> None:
        """Check if the new result has the best QoR and update it if so.
           Note that we allow value overwritten in the database for the
           performance issue, although it should not happen during the
           search. However, the best cache may keep the overrided result
           so this could be a potential issue.

        Parameters
        ----------
        result:
            The new result to be checked.
        """

        try:
            self.best_cache.put((result.quality, time(), result))
        except Exception as err:
            self.log.error('Failed to update best cache: %s', str(err))
            raise RuntimeError()

    def commit(self, key: str, result: Any) -> None:
        """Commit a new result to the database

        Parameters
        ----------
        key:
            The key of a design point.

        result:
            The result to be committed.
        """

        if not self.commit_impl(key, result):
            self.log.error('Failed to commit results to the database')
            raise RuntimeError()

        if isinstance(result, Result):
            self.update_best(result)

    def batch_commit(self, pairs: List[Tuple[str, Any]]) -> None:
        """Commit a set of new results to the database.

        Parameters
        ----------
        pairs:
            A list of key-result pairs
        """

        if self.batch_commit_impl(pairs) != len(pairs):
            self.log.error('Failed to commit results to the database')
            raise RuntimeError()

        # Update the best result
        for _, result in pairs:
            if isinstance(result, Result):
                self.update_best(result)

    def query_all(self) -> List[Any]:
        """Query all values in the database

        Returns
        -------
        List[Any]:
            All data in the database
        """
        return [v for v in self.batch_query(self.query_keys()) if v is not None]

    def count_ret_code(self, ret_code: Result.RetCode) -> int:
        """Count the number of results with the given return code

        Parameters
        ----------
        ret_code:
            The return code to be counted.

        Returns
        -------
        int:
            The number of results with the return code.
        """

        return len(
            [r for r in self.query_all() if isinstance(r, Result) and r.ret_code == ret_code])

    def load(self) -> None:
        """Load existing data from the given database and update the best cahce (if available)"""
        raise NotImplementedError()

    def query(self, key: str) -> Optional[Any]:
        """Query for the value by the given key

        Parameters
        ----------
        key:
            The key of a design point.

        Returns
        -------
        Optional[Any]:
            The result object of the corresponding key, or None if the key is unavailable.
        """
        raise NotImplementedError()

    def batch_query(self, keys: List[str]) -> List[Optional[Any]]:
        """Query for a list of the values by the given key list

        Parameters
        ----------
        key:
            The key of a design point.

        Returns
        -------
        Optional[Any]:
            The result object of the corresponding key, or None if the key is unavailable.
        """
        raise NotImplementedError()

    def query_keys(self) -> List[str]:
        """Return all keys"""
        raise NotImplementedError()

    def commit_impl(self, key: str, result: Any) -> bool:
        """Commit function implementation.

        Parameters
        ----------
        key:
            The key of a design point.

        result:
            The result to be committed.

        Returns
        -------
        bool:
            True if the commit was success; otherwise False.
        """
        raise NotImplementedError()

    def batch_commit_impl(self, pairs: List[Tuple[str, Any]]) -> int:
        """Batch commit function implementation.

        Parameters
        ----------
        pairs:
            A list of key-result pairs.

        Returns
        -------
        int:
            Indicate the number of committed data.
        """
        raise NotImplementedError()

    def count(self) -> int:
        """Count total number of data points in the database

        Returns
        -------
        int:
            Total number of data points
        """
        raise NotImplementedError()

    def persist(self) -> bool:
        """Persist the DB by dumping it to a pickle file and close the DB

        Returns
        -------
        bool:
            True if the dumping and close was success; otherwise False.

        """
        raise NotImplementedError()


class RedisDatabase(Database):
    """The database implementation using Redis"""

    def __init__(self, name: str, cache_size: int = 1, db_file_path: Optional[str] = None):
        super(RedisDatabase, self).__init__(name, cache_size, db_file_path)

        import redis

        #TODO: scale-out
        self.database = redis.StrictRedis(host='localhost', port=6379)

        # Check the connection
        try:
            self.database.client_list()
        except redis.ConnectionError:
            raise RuntimeError()

    def load(self) -> None:
        #pylint:disable=missing-docstring

        # Load existing data
        # Note that the dumped data for RedisDatabase should be in pickle format
        if os.path.exists(self.db_file_path):
            with open(self.db_file_path, 'rb') as filep:
                try:
                    data = pickle.load(filep)
                except ValueError as err:
                    self.log.error('Failed to initialize the database: %s', str(err))
                    raise RuntimeError()
            self.log.info('Load %d data from an existing database', len(data))
            self.database.hmset(self.db_id, data)

        self.init_best_cache()
        self.init_code_hash_set()

    def __del__(self):
        """Delete the data we generated in Redis database"""
        if self.database:
            self.database.delete(self.db_id)

    def query(self, key: str) -> Optional[Any]:
        #pylint:disable=missing-docstring

        if not self.database.hexists(self.db_id, key):
            return None

        pickled_obj = self.database.hget(self.db_id, key)
        if pickled_obj:
            try:
                return pickle.loads(pickled_obj)
            except ValueError as err:
                self.log.error('Failed to deserialize the result of %s: %s', key, str(err))
        return None

    def batch_query(self, keys: List[str]) -> List[Optional[Any]]:
        #pylint:disable=missing=docstring

        if not keys:
            return []

        data = []

        for key, pickled_obj in zip(keys, self.database.hmget(self.db_id, keys)):
            if pickled_obj:
                try:
                    data.append(pickle.loads(pickled_obj))
                except ValueError as err:
                    self.log.error('Failed to deserialize the result of %s: %s', key, str(err))
                    data.append(None)
            else:
                data.append(None)
        return data

    def query_keys(self) -> List[str]:
        #pylint:disable=missing-docstring
        return [k.decode(encoding='UTF-8') for k in self.database.hkeys(self.db_id)]

    def commit_impl(self, key: str, result: Any) -> bool:
        #pylint:disable=missing-docstring

        pickled_result = pickle.dumps(result)
        self.database.hset(self.db_id, key, pickled_result)
        return True

    def batch_commit_impl(self, pairs: List[Tuple[str, Any]]) -> int:
        #pylint:disable=missing-docstring

        data = {key: pickle.dumps(result) for key, result in pairs}
        self.database.hmset(self.db_id, data)
        return len(data)

    def count(self) -> int:
        #pylint:disable=missing-docstring
        return len(self.database.hkeys(self.db_id))

    def persist(self) -> bool:
        #pylint:disable=missing-docstring

        dump_db = {
            key: self.database.hget(self.db_id, key)
            for key in self.database.hgetall(self.db_id)
        }
        with open(self.db_file_path, 'wb') as filep:
            pickle.dump(dump_db, filep, pickle.HIGHEST_PROTOCOL)

        return True


class PickleDatabase(Database):
    """
    The database implementation using PickleDB

    This is an alternative when other databases are unavailable in the system.
    Note that it is discouraged to use this database for DSE due to poor performance
    and the lack of multi-node support.
    """

    def __init__(self, name: str, cache_size: int = 1, db_file_path: Optional[str] = None):
        super(PickleDatabase, self).__init__(name, cache_size, db_file_path)

        import pickledb
        self.lock = Lock()

        try:
            # Load the Pickle database
            # Note that we cannot enable auto dump since we will pickle all data before persisting
            self.database: pickledb.PickleDB = pickledb.load(self.db_file_path, False)
        except ValueError as err:
            self.log.error('Failed to initialize the database: %s', str(err))
            raise RuntimeError()

    def load(self) -> None:
        #pylint:disable=missing-docstring
        import jsonpickle

        try:
            # Decode objects
            for key in self.database.getall():
                obj = jsonpickle.decode(self.database.get(key))
                self.database.set(key, obj)
            self.log.info('Load %d data from an existing database', self.count())
        except ValueError as err:
            self.log.error('Failed to load the data from the database: %s', str(err))
            raise RuntimeError()

        self.init_best_cache()
        self.init_code_hash_set()

    def query(self, key: str) -> Optional[Any]:
        #pylint:disable=missing-docstring

        self.lock.acquire()
        value: Union[bool, Result] = self.database.get(key)
        self.lock.release()
        return None if isinstance(value, bool) else value

    def batch_query(self, keys: List[str]) -> List[Optional[Any]]:
        #pylint:disable=missing=docstring

        if not keys:
            return []

        self.lock.acquire()
        values: List[Optional[Any]] = []
        for key in keys:
            value = self.database.get(key)
            values.append(None if isinstance(value, bool) else value)
        self.lock.release()
        return values

    def query_keys(self) -> List[str]:
        #pylint:disable=missing-docstring
        return list(self.database.getall())

    def commit_impl(self, key: str, result: Result) -> bool:
        #pylint:disable=missing-docstring

        self.lock.acquire()
        self.database.set(key, result)
        self.lock.release()
        return True

    def batch_commit_impl(self, pairs: List[Tuple[str, Any]]) -> int:
        #pylint:disable=missing-docstring

        self.lock.acquire()
        for key, result in pairs:
            self.database.set(key, result)
        self.lock.release()
        return len(pairs)

    def count(self) -> int:
        #pylint:disable=missing-docstring
        return self.database.totalkeys()

    def persist(self) -> bool:
        #pylint:disable=missing-docstring

        import jsonpickle
        # Pickle all results so that they are JSON seralizable
        for key in self.database.getall():
            pickled_obj = jsonpickle.encode(self.database.get(key))
            self.database.set(key, pickled_obj)

        return self.database.dump()
