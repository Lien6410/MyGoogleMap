import os


def load_env(path='.env'):
    env = {}
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class DbConfig:
    def __init__(self, host, port, dbname, user, password):
        self.host = host
        self.port = port
        self.dbname = dbname
        self.user = user
        self._password = password

    @classmethod
    def from_env(cls, env=None, dbname_key='PGDATABASE'):
        if env is None:
            env = {**load_env(), **os.environ}
        return cls(
            host=env.get('PGHOST', 'localhost'),
            port=env.get('PGPORT', '5432'),
            dbname=env.get(dbname_key, ''),
            user=env.get('PGUSER', ''),
            password=env.get('PGPASSWORD', ''),
        )

    def conninfo(self):
        return (f"host={self.host} port={self.port} dbname={self.dbname} "
                f"user={self.user} password={self._password}")

    def safe_dict(self):
        return {'host': self.host, 'port': self.port,
                'dbname': self.dbname, 'user': self.user}

    def __repr__(self):
        return f"DbConfig({self.safe_dict()}, password=***)"
