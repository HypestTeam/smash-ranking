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
import datetime

# set up the parser
parser = argparse.ArgumentParser()
parser.add_argument("--bracket", "-b", help="the challonge URL bracket to check", metavar="<url>", required=True)
parser.add_argument("--quiet", "-q", help="suppress some output", action="store_true")
parser.add_argument("--dry-run", help="output to stdout instead of publishing changes", action="store_true")
parser.add_argument("--new", help="shows the new users to be added to ranking without adding them, implies --dry-run", action="store_true")
parser.add_argument("--dump", help="dumps the appropriate JSON response", action="append", choices=["tournament", "players"], default=[], metavar="<type>")
parser.add_argument("--player", help="show player info of the bracket and exit", action="store_true")
parser.add_argument("--force", help="forces a player to be processed. Format must have the reddit username first and then the ranking", nargs='*', action="append", default=[])
parser.add_argument("--remove", help="removes a player from processing", nargs="*", metavar="<name>", action="append", default=[])
args = parser.parse_args()

if args.new:
    args.dry_run = True

class User(object):
    __slots__ = ["score", "name", "change", "forced"]
    def __init__(self, score, name, change, forced=False):
        self.score = score
        self.name = name
        self.change = change
        # this specifies that the user has been 'forced' through --force
        # so the presence of this being != False then it means it's already been processed through the
        # username retrieval process
        self.forced = forced

class RankJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        else:
            return super(RankJsonEncoder, self).default(obj)

# loads the challonge database which is "challonge username": "reddit username"
challonge_json = open(os.path.join("database", "challonge.json"))
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

# gets the reddit username associated with the challonge username
def get_username(user):
    if user.forced:
        return user.name
    return usernames.get(user.name.lower(), None) if user.name != None else None

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
            result.append(User(score=rank, name=name, change=0))

    # remove players
    if len(args.remove) > 1:
        for user in result:
            for removal in args.remove:
                if removal == user.name:
                    user.name = None

    # add the forced player
    for user in args.force:
        result.append(User(score=int(user[1]), name=user[0], change=0, forced=True))

    # sort and remove actual entries
    result = [user for user in result if user.name != None]
    result.sort(key=lambda x: x.score)
    return result

# get the database file name
def get_database_file(tournament):
    game_id = tournament["game-id"]
    if game_id == 16869: # Smash Bros for 3DS
        return os.path.join("database", "3ds.json")
    elif game_id == 597: # Project M
        return os.path.join("database", "projectm.json")
    elif game_id == 394: # Smash Bros Melee
        return os.path.join("database", "melee.json")
    else:
        return '' # not supported

# returns the actual dictionary containing the database
def get_database(tournament):
    filename = get_database_file(tournament)
    if filename:
        with open(filename) as f:
            return json.load(f)
    return None

def updated_ranking(tournament, db):
    # get an old back-up of the database to do a change compare later
    old = [User(name=k, score=v, change=0) for (k, v) in iter_dict(db)]
    old.sort(key=lambda x: x.score, reverse=True)
    ranks = get_top(7, tournament)

    # update the ranking
    for user in ranks:
        name = get_username(user)
        if name:
            if name in db:
                db[name] = db[name] + points[user.score]
            else:
                if args.new:
                    print("new user /u/{}".format(name))
                    continue
                db[name] = points[user.score]

    # compare the change in ranking
    result = [User(name=k, score=v, change=0) for (k, v) in iter_dict(db)]
    result.sort(key=lambda x: x.score, reverse=True)

    for i, user in enumerate(result):
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
    result.append("**Change**|**Rank**|**Player**|**Score**")
    result.append(":---------|:-------|----------|---------")
    for i, user in enumerate(users):
        result.append("{0.change:+}|{1}|/u/{0.name}|{0.score}".format(user, i + 1))
    return '\n'.join(result)

# saves the database with the result of the tournament
def publish_database(tournament, db):
    filename = get_database_file(tournament)
    with open(filename) as f:
        json.dump(db, f, sort_keys=True, indent=4, separators=(',', ': '), cls=RankJsonEncoder)

# login to challonge to use the API. Credentials must be in database/login.json
# the format should be { "challonge": { "username": "", "key": "" }}
def login():
    obj = None
    with open(os.path.join("database", "login.json")) as f:
        obj = json.load(f)

    challonge_credentials = obj["challonge"]
    challonge.set_credentials(challonge_credentials["username"], challonge_credentials["key"])

def player_list(tournament, db):
    ranks = get_top(7, tournament)
    print("Challonge Username | Reddit Username")
    for user in ranks:
        reddit = get_username(user)
        print("{0:<18} | {1:<18}".format(user.name, reddit))

if __name__ == "__main__":
    login()
    tournament = get_tournament(args.bracket)
    db = get_database(tournament)

    if not args.quiet:
        print("Tournament ID: {}".format(tournament["id"]))
        print("Tournament Name: {}".format(tournament["name"]))

    if "tournament" in args.dump:
        print(json.dumps(tournament, sort_keys=True, indent=4, separators=(',', ': '), cls=RankJsonEncoder))

    if args.player:
        player_list(tournament, db)
        exit(0)

    users = updated_ranking(tournament, db)
    print(markdown_table(users))
