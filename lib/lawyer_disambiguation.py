#!/usr/bin/env Python
"""
Performs a basic lawyer disambiguation
"""
from collections import defaultdict, deque
import uuid
import cPickle as pickle
from collections import Counter
from Levenshtein import jaro_winkler
from alchemy import grantsession, get_config, match
from alchemy.schema import *
from handlers.xml_util import normalize_utf8
from datetime import datetime
from sqlalchemy.sql import or_
from sqlalchemy.sql.expression import bindparam
import sys
config = get_config()

THRESHOLD = config.get("lawyer").get("threshold")

# bookkeeping for blocks
blocks = defaultdict(list)
id_map = defaultdict(list)
lawyers = []
lawyer_dict = {}


def get_lawyer_id(obj):
    """
    Returns string representing a rawlawyer object. Returns obj.organization if
    it exists, else returns concatenated obj.name_first + '|' + obj.name_last
    """
    if obj.organization:
        return obj.organization
    try:
        return obj.name_first + '|' + obj.name_last
    except:
        return ''

def clean_lawyers(list_of_lawyers):
    """
    Removes the following stop words from each lawyer:
    the, of, and, a, an, at
    Then, blocks the lawyer with other lawyers that start
    with the same letter. Returns a list of these blocks
    """
    stoplist = ['the', 'of', 'and', 'a', 'an', 'at']
    alpha_blocks = defaultdict(list)
    print 'Removing stop words, blocking by first letter...'
    for lawyer in list_of_lawyers:
        lawyer_dict[lawyer.uuid] = lawyer
        l_id = get_lawyer_id(lawyer)
        # removes stop words, then rejoins the string
        l_id = ' '.join(filter(lambda x:
                            x.lower() not in stoplist,
                            l_id.split(' ')))
        id_map[l_id].append(lawyer.uuid)
        alpha_blocks[l_id[0]].append(l_id)
    print 'Alpha blocks created!'
    return alpha_blocks.itervalues()


def create_jw_blocks(list_of_lawyers):
    """
    Receives list of blocks, where a block is a list of lawyers
    that all begin with the same letter. Within each block, does
    a pairwise jaro winkler comparison to block lawyers together
    """
    consumed = defaultdict(int)
    print 'Doing pairwise Jaro-Winkler...'
    for alphablock in list_of_lawyers:
        for primary in alphablock:
            if consumed[primary]: continue
            consumed[primary] = 1
            blocks[primary].append(primary)
            for secondary in alphablock:
                if consumed[secondary]: continue
                if primary == secondary:
                    blocks[primary].append(secondary)
                    continue
                if jaro_winkler(primary, secondary, 0.0) >= THRESHOLD:
                    consumed[secondary] = 1
                    blocks[primary].append(secondary)
    pickle.dump(blocks, open('lawyer.pickle', 'wb'))
    print 'lawyer blocks created!'


def create_lawyer_table():
    """
    Given a list of lawyers and the redis key-value disambiguation,
    populates the lawyer table in the database
    """
    print 'Disambiguating lawyers...'
    i = 0
    for lawyer in blocks.iterkeys():
        rl_ids = (id_map[ra] for ra in blocks[lawyer])
        for block in rl_ids:
          i += 1
          rawlawyers = [lawyer_dict[rl_id] for rl_id in block]
          if i % 10000 == 0:
              match(rawlawyers, grantsession, commit=True)
          else:
              match(rawlawyers, grantsession, commit=False)
    grantsession.commit()

def examine():
    lawyers = s.query(lawyer).all()
    for a in lawyers:
        print get_lawyer_id(a), len(a.RawLawyers)
        for ra in a.rawlawyers:
            if get_lawyer_id(ra) != get_lawyer_id(a):
                print get_lawyer_id(ra)
            print '-'*10
    print len(lawyers)


def printall():
    lawyers = s.query(lawyer).all()
    with open('out.txt', 'wb') as f:
        for a in lawyers:
            f.write(normalize_utf8(get_lawyer_id(a)).encode('utf-8'))
            f.write('\n')
            for ra in a.rawlawyers:
                f.write(normalize_utf8(get_lawyer_id(ra)).encode('utf-8'))
                f.write('\n')
            f.write('-'*20)
            f.write('\n')

def run_letter(letter):
    letter = letter.upper()
    clause1 = RawLawyer.organization.startswith(bindparam('letter',letter))
    clause2 = RawLawyer.name_first.startswith(bindparam('letter',letter))
    clauses = or_(clause1, clause2)
    lawyers = (lawyer for lawyer in grantsession.query(RawLawyer).filter(clauses))
    block = clean_lawyers(lawyers)
    create_jw_blocks(block)
    create_lawyer_table()

def run_disambiguation():
    lawyers = deque(grantsession.query(RawLawyer))
    lawyer_alpha_blocks = clean_lawyers(lawyers)
    create_jw_blocks(lawyer_alpha_blocks)
    create_lawyer_table()


if __name__ == '__main__':
    if len(sys.argv) < 2:
      run_disambiguation()
    else:
      letter = sys.argv[1]
      print ('Running ' + letter)
      run_letter(letter)
