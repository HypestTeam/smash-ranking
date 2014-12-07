#!/usr/bin/env python
# The MIT License (MIT)

# Copyright (c) 2014 Rapptz

# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

# Created for /r/smashbros ranking system

import challonge
import argparse
import re, os, json, sys
import decimal
import urllib
import datetime

# set up the parser
parser = argparse.ArgumentParser()
parser.add_argument("--bracket", "-b", help="the challonge URL bracket to check", metavar="<url>")
parser.add_argument("--game", help="the game file to edit; implies --table-only", metavar="<file>")
parser.add_argument("--quiet", "-q", help="suppress some output", action="store_true")
parser.add_argument("--dry-run", help="output to stdout instead of publishing changes", action="store_true")
parser.add_argument("--dump", help="dumps the appropriate JSON response", action="append", choices=["tournament", "players"], default=[], metavar="<type>")
parser.add_argument("--player", help="show player info of the bracket and exit", action="store_true")
parser.add_argument("--add", help="adds a player to be processed. Format must have the challonge first and then the ranking", nargs='*', action="append", default=[])
parser.add_argument("--remove", help="removes a player from processing", nargs="*", metavar="<name>", action="append", default=[])
parser.add_argument("--force", help="forces processing despite cache", action="store_true")
parser.add_argument("--table-only", help="doesn't process a tournament and just prints the ladder; implies --dry-run", action="store_true")
args = parser.parse_args()

if args.game != None:
    args.table_only = True

if args.table_only:
    args.dry_run = True

if args.bracket == None and args.game == None:
    parser.error('either --game or --bracket are required')

challonge_path = os.path.join("database", "challonge.json")
cache_path = os.path.join("database", "cache.json")
login_path = os.path.join("database", "login.json")

if not os.path.exists("database"):
    parser.error("database directory required for this program to run")

if not os.path.exists(challonge_path):
    parser.error("{} file is required for challonge to reddit username mappings".format(challonge_path))

if not os.path.exists(login_path):
    parser.error("{} file is required for login credentials".format(login_path))

class User(object):
    __slots__ = ["score", "name", "reddit", "change"]
    def __init__(self, score, name, reddit=None, change=0):
        self.score = score     # the total score in ranking
        self.name = name       # the challonge username
        self.reddit = reddit   # the reddit username
        self.change = change   # the change in ranking placing

class RankJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        elif isinstance(obj, decimal.Decimal):
            return float(obj)
        elif isinstance(obj, set):
            return list(obj)
        else:
            return super(RankJsonEncoder, self).default(obj)

# loads the challonge database which is "challonge username": "reddit username"
challonge_json = open(challonge_path)
usernames = json.load(challonge_json)

# placing to points
points = {
    1: 10, # 1st place points
    2: 8,  # 2nd place points
    3: 6,  # 3rd place points
    4: 4,  # 4th place points
    5: 2,  # 5th place points
    7: 1   # 7th place points
}

# check the old rank in the leaderboards for the user. None if not found.
# currently uses a lame O(n) approach. It'll be a binary search i.e. O(log n)
# if this turns out to be an issue
def get_old_rank(old_db, check):
    for i, user in enumerate(old_db):
        if user.name == check.name:
            return i
    return None


# gets the reddit username through a string rather than a user
def get_raw_username(name):
    result = usernames.get(name.lower(), None) if name != None else None
    if result == None:
        # since we couldn't find the name, maybe /u/challongeusername is valid
        # which would be a reasonable default
        response = urllib.urlopen('http://www.reddit.com/user/' + name)
        if response.getcode() == 200:
            result = name
            usernames[name] = name
    return result

# gets the reddit username associated with the challonge username
def get_username(user):
    if user.reddit:
        return user.reddit
    return get_raw_username(user.name)

# python 3k compatibility function
def iter_dict(dictionary):
    if sys.version_info[0] == 3:
        return dictionary.items()
    else:
        return dictionary.iteritems()

# get the tournament object of a url
def get_tournament(url):
    # remove http(s?):// from the url
    new_url = re.sub(r"https?:\/\/", "", url)
    # remove challonge.com from the url
    new_url = new_url.replace("challonge.com/", "")
    # at this point the url is subdomain.tournament_id
    fragments = new_url.split('.')
    if len(fragments) == 2:
        organisation = challonge.tournaments.index(subdomain=fragments[0])
        for tournament in organisation:
            if tournament["full-challonge-url"] == url:
                return challonge.tournaments.show(tournament["id"])

    # if we're here then there was no subdomain found
    return challonge.tournaments.show(new_url)

# get the top finalised participants of a tournament
def get_top(limit, tournament):
    if tournament["state"] != "complete":
        parser.error('tournament not complete')

    participants = challonge.participants.index(tournament["id"])
    if "players" in args.dump:
        print(json.dumps(participants, sort_keys=True, indent=4, separators=(',', ': '), cls=RankJsonEncoder))

    result = []
    for participant in participants:
        rank = participant["final-rank"]
        if rank != None and rank <= limit:
            name = participant["challonge-username"]
            if name == None:
                continue
            reddit = get_raw_username(name)
            result.append(User(score=rank, reddit=reddit, name=name, change=0))

    # add the forced player
    for user in args.add:
        name = user[0]
        reddit = get_raw_username(name)
        result.append(User(score=int(user[1]), name=name, reddit=reddit, change=0))

    # sort and remove actual entries
    result = [user for user in result if user.name not in args.remove]
    result.sort(key=lambda x: x.score)
    return result

# get the database file name
def get_database_file(tournament):
    # a quick shortcut if --game is provided
    if args.game:
        return os.path.join("database", "{}.json".format(args.game))
    game_id = tournament["game-id"]
    if game_id == 16869: # Smash Bros for 3DS
        return os.path.join("database", "3ds.json")
    elif game_id == 20988: # Smash Bros fro Wii U
        return os.path.join("database", "wiiu.json")
    elif game_id == 597: # Project M
        return os.path.join("database", "projectm.json")
    elif game_id == 394: # Smash Bros Melee
        return os.path.join("database", "melee.json")
    elif game_id == 1106: # Super Smash Flash 2
        return os.path.join("database", "flash.json")
    elif game_id == 392: # Super Smash Bros. (i.e. N64)
        return os.path.join("database", "64.json")
    else:
        return '' # not supported

# returns the actual dictionary containing the database
def get_database(tournament):
    filename = get_database_file(tournament)
    if filename:
        if os.path.exists(filename):
            with open(filename) as f:
                return json.load(f)
        else:
            return dict()
    return None

def load_cache():
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return set(json.load(f))
    else:
        return set()

def updated_ranking(tournament, db):
    # get an old back-up of the database to do a change compare later
    old = [User(name=k, score=v, change=0) for (k, v) in iter_dict(db)]
    old.sort(key=lambda x: x.score, reverse=True)
    ranks = get_top(7, tournament)

    # update the ranking
    for user in ranks:
        if user.name in db:
            db[user.name] = db[user.name] + points[user.score]
        else:
            db[user.name] = points[user.score]

    # compare the change in ranking
    result = [User(name=k, score=v, change=0) for (k, v) in iter_dict(db)]
    result.sort(key=lambda x: x.score, reverse=True)

    for i, user in enumerate(result):
        user.reddit = get_raw_username(user.name)
        old_index = get_old_rank(old, user)
        if old_index == None:
            user.change = i
        else:
            user.change = old_index - i

    return result

def markdown_table(users):
    today = datetime.datetime.now()
    result = []
    # if a comment is needed to separate, it'd be put here
    result.append(today.strftime("*Last Updated: %c*"))
    result.append("")
    result.append("**Change**|**Rank**|**Challonge User**|**Reddit User**|**Score**")
    result.append(":---------|:-------|:-----------------|:--------------|:--------:")
    for i, user in enumerate(users):
        reddit = "/u/" + user.reddit if user.reddit else "Unknown"
        result.append("{0.change:+}|{1}|[{0.name}](http://www.challonge.com/users/{0.name})|{2}|{0.score}".format(user, i + 1, reddit))
    return '\n'.join(result)

# saves the database with the result of the tournament
def update_database(tournament, db):
    filename = get_database_file(tournament)
    with open(filename, 'w') as f:
        json.dump(db, f, sort_keys=True, indent=4, separators=(',', ': '), cls=RankJsonEncoder)

def update_cache(cache):
    with open(cache_path, 'w') as f:
        json.dump(cache, f, sort_keys=True, indent=4, separators=(',', ': '), cls=RankJsonEncoder)

def update_mapping():
    with open(challonge_path, 'w') as f:
        json.dump(usernames, f, sort_keys=True, indent=4, separators=(',', ': '), cls=RankJsonEncoder)

# login to challonge to use the API. Credentials must be in database/login.json
# the format should be { "challonge": { "username": "", "key": "" }}
def login():
    obj = None
    with open(login_path) as f:
        obj = json.load(f)

    challonge_credentials = obj["challonge"]
    challonge.set_credentials(challonge_credentials["username"], challonge_credentials["key"])

def player_list(tournament, db):
    ranks = get_top(7, tournament)
    print("{0:<20} | {1:<20} | {2}".format("Challonge Username", "Reddit Username", "Rank"))
    for user in ranks:
        reddit = get_username(user)
        print("{0:<20} | {1:<20} | {2}".format(user.name, reddit, user.score))

if __name__ == "__main__":
    cache = load_cache()
    if args.bracket in cache and not args.force:
        print('bracket already processed use --force to process it again')
        exit(0)

    cache.add(args.bracket)
    login()
    db = None
    tournament = None
    if args.bracket:
        tournament = get_tournament(args.bracket)
        db = get_database(tournament)
    else:
        db = get_database(None)

    if not args.quiet:
        print("Tournament ID: {}".format(tournament["id"]))
        print("Tournament Name: {}".format(tournament["name"]))
        print("Tournament File: {}".format(get_database_file(tournament)))

    if "tournament" in args.dump:
        print(json.dumps(tournament, sort_keys=True, indent=4, separators=(',', ': '), cls=RankJsonEncoder))

    if args.table_only:
        result = [User(name=k, score=v, reddit=get_raw_username(k)) for k, v in iter_dict(db)]
        result.sort(key=lambda x: x.score, reverse=True)
        print(markdown_table(result))
    elif args.player:
        player_list(tournament, db)
    else:
        users = updated_ranking(tournament, db)
        print(markdown_table(users))
        if not args.dry_run:
            update_database(tournament, db)
            update_mapping()
            update_cache(cache)
