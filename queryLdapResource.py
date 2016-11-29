""" this script also requires a config file 'config.cfg'. Just copy and rename
    the config.cfg.tmpl. You can find it in this same directory
"""
import MySQLdb
import json
import requests
import base64
import ConfigParser

from time import sleep

""" Reads the config file to pull usernames, passwords.
"""
def readConfig():
    config = ConfigParser.RawConfigParser()
    config.read('config.cfg')
    return {
        'dbUser' : config.get('mysql', 'username'),
        'dbPass' : config.get('mysql', 'password'),
        'dbName' : config.get('mysql', 'database'),
        'dbHost' : config.get('mysql', 'host'),
        'ldapUser': config.get('ldap', 'username'),
        'ldapPass': config.get('ldap', 'password')
    }

""" Authenticate against the LDAP server. credentials should be in format
    user:pass and we need to base64 encode our credentials to authenticate
    on the LDAP server because we are sending the credentials using the
    header:
        Authentication: Basic xxxx
    Where xxx are the base64encoded credentials
"""
def authenticate(config, crashReportsUrl):
    usrPass = config['ldapUser'] + ':' + config['ldapPass']
    b64Val = base64.b64encode(usrPass)
    headers = {"Authorization": "Basic %s" % b64Val}
    r = requests.get(crashReportsUrl,
                     headers=headers)
    return r

""" Performs a request to the search endpoint which returns a JSON string
    (just add or remove .json to the /search endpoint)

    Sample response:
    https://crashreports.thefoundry.co.uk/search.json?query=6efc7ec5-2b21-cd20-514cfa47-12a95093.dmp&type=uuids
"""
def performRequest(config, crashReportNameId):
    crashReportsUrl = 'https://crashreports.thefoundry.co.uk/search.json?query=' + crashReportNameId + '&type=uuids'
    response = authenticate(config, crashReportsUrl)
    statusCode = response.status_code
    content = json.loads(response.content)

    # NOTE: the field 'crash_reports' of the response returns an array of crash
    # reports so we have to perform another loop to find each crash report
    if statusCode == 200 and len(content['crash_reports']) != 0:
        return content['crash_reports']
    else:
        print "Error connecting to the LDAP server or empty response."
        return False

""" The connect() constructor creates a connection to the MySQL server and
    returns a MySQLConnection object.
"""
def connectToDatabase(config):
    try:
        cnx = MySQLdb.connect(user=config['dbUser'],
                              passwd=config['dbPass'],
                              host=config['dbHost'],
                              db=config['dbName'])
        return cnx

    except MySQLdb.Error, e:
        print "Failed connecting to database: %s" % str(e)
        exit(1)

""" Finds all records in testdb1.crash_reports where the upload_id is null.
    This function returns an array of names where each entry is a crash_report
    row where the ID is missing (NULL)
"""
def findMissingRecords(cnx):
    missingRecords = []
    cursor = cnx.cursor()
    try:
        cursor.execute("SELECT name, upload_id FROM crash_reports WHERE upload_id IS NULL LIMIT 1")
        for (name, upload_id) in cursor:
            missingRecords.append(name)

        return missingRecords

    except MySQLdb.Error, e:
        print "Error fetching data: %s" % str(e)
        exit(1)

""" Takes an array of crash_report names where the ID is null (records) and attemp
    to find the missing ID by querying the crash reports website.
"""
def updateMissingRecords(config, records, cnx):
    crashReportIds = {}
    cursor = cnx.cursor()

    # This is the main loop, if we grabbed, say 10.000 records it will iterate
    # over the 10.000 records, perform one request per record (or more than one if
    # the crashReportsResponse contains more than one crash report) and then update
    # the database.
    # This way we don't have to create a massive object with 10.000 records and then
    # stress the database updating all 10.000 records in one go without waiting some
    # time.

    for elem in range(0, len(records)):

        # NOTE: the function 'performRequest()' returns an array of crash reports
        # so we have to perform another loop to find each individual crash report
        # NOTE: sleep every 100ms to avoid flooding the crash reports site

        print "Attempting to parse report " + records[elem]
        crashReportsResponse = performRequest(config, records[elem])

        print 'Request sent, sleeping for 100ms'
        sleep(0.1)

        # skip the current element if we receive a blank response (it can happen
        # that some reports cannot be found on the crashreports site)
        # NOTE: we set the upload_id to 0 to make sure that we don't pull this crash
        # report again the next time we run this script (remember that the initial
        # query grabs all entries where upload_id is null)

        # if crashReportsResponse == False:
        #     query = "UPDATE crash_reports SET upload_id = 0 WHERE name = \"%s\" AND upload_id IS NULL;"
        #     print query % records[elem]
        #     cursor.execute(query, records[elem])
        #     # cnx.commit()
        #     continue

        for crashReport in range(0, len(crashReportsResponse)):

            # creates a dictionary where keys are the crash report IDs and values the crash report names
            # we can use a dictionary instead of a list because the IDs are unique so we'll always have unique
            # keys

            crashReportId = crashReportsResponse[crashReport]["id"]
            crashReportName = crashReportsResponse[crashReport]["file"]["name"]
            crashReportIds[crashReportId] = crashReportName
            print "Parsed crash report " + crashReportName


        # Now that we have all the details, update the database
        try:
            for crashId, crashName in crashReportIds.items():

                query = "UPDATE crash_reports SET upload_id = %s WHERE name = \"%s\" AND upload_id IS NULL"
                cursor.execute(query, (crashId, crashName))

            # commit transaction and clear crashReportIds object to prevent stacking old elements
            crashReportIds = {}

        except MySQLdb.Error, e:
            print "Error updating data: %s" % str(e)
            exit(1)

    cnx.commit()
    cnx.close()
    exit(0)


def main():
    """ if we want to get rid of SSL warnings we need to install the following packages
        Debian/Ubuntu: python-dev libffi-dev libssl-dev packages.
        Fedora - openssl-devel python-devel libffi-devel packages.
        source: # http://stackoverflow.com/questions/29099404/ssl-insecureplatform-error-when-using-requests-package
    """
    requests.packages.urllib3.disable_warnings()
    config = readConfig()

    cnx = connectToDatabase(config)
    # cnx.autocommit(True)
    records = findMissingRecords(cnx)
    crashReportIds = updateMissingRecords(config, records, cnx)

    print crashReportIds

if __name__ == "__main__":
        main()