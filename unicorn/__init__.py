"""The Unicorn Django project.

The database driver is `mysqlclient` where it can be built. On a server without the database development files
(and where nothing may be installed from a repository), the pure-Python `PyMySQL` stands in for it
(CLAUDE.md, section 4; P15.T04). Django only needs to be told that it is "mysqlclient", and of which version.
"""

try:
    import MySQLdb  # noqa: F401
except ImportError:  # no mysqlclient: use PyMySQL under its name
    try:
        import pymysql
    except ImportError:  # neither is installed: Django will say so when the database is used
        pass
    else:
        pymysql.version_info = (2, 2, 1, "final", 0)  # Django 5.2 asks for mysqlclient 2.2.1 or newer
        pymysql.install_as_MySQLdb()
