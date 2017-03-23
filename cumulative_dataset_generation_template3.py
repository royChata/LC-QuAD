'''This file specifically generates dataset for template 3 with a given set of entites.'''

# Importing some external libraries
from pprint import pprint
import networkx as nx
import pickle
import json
import copy
import traceback
import random

# Importing internal classes/libraries
import utils.dbpedia_interface as db_interface
import utils.natural_language_utilities as nlutils
import utils.subgraph as subgraph
import time

# @TODO: put this class there

'''
    Initializing some stuff. Namely: DBpedia interface class.
    Reading the list of 'relevant' properties.
'''

dbp = None  # DBpedia interface object #To be instantiated when the code is run by main script/unit testing script
relevant_properties = open('resources/relation_whitelist.txt').read().split('\n')  # Contains the whitelisted props types
relevent_entity_classes = open('resources/entity_classes.txt').read().split('\n') #Contains whitelisted entities classes
list_of_entities = open('resources/entities.txt').read().split('\n')
'''contains list of entites for which the question would be asked '''

templates = json.load(open('templates.py'))  # Contains all the templates existing in templates.py
sparqls = {}  # Dict of the generated SPARQL Queries.
properties_count = {}
''' dictionary of properties. with key being the parent entity and value would be a dictionary with key peing name
    of property and value being number of times it has already occured .
    {"/agent" : [ {"/birthPlace" : 1 }, {"/deathPlace" : 2}] }
    '''
'''
    Some SPARQL Queries.
    Since this part of the code requires sending numerous convoluted queries to DBpedia,
        we best not clutter the DBpedia interface class and rather simply declare them here.

    Note: The names here can be confusing. Refer to the diagram above to know what each SPARQL query tries to do.
'''

one_triple_right = '''
            SELECT DISTINCT ?p ?e
            WHERE {
                <%(e)s> ?p ?e.

            }'''

one_triple_left = '''
            SELECT DISTINCT ?e ?p ?type
            WHERE {
                ?e ?p <%(e)s>.

            }'''

'''
    ?e <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?type
    This cell houses the script which will build a subgraph as shown in picture above for each a given URI.
    @TODO: do something in cases where certain nodes of the local subgraph are not found.
            Will the code throw errors? How to you take care of them?
'''


def pruning(_results, _keep_no_results = 100, _filter_properties = True, _filter_literals = True, _filter_entities = True ):
    '''
    Function: Implements pruing in the results . used to push the results of different queries into the subgraph.
        >First prunes based on properties and entite classes. After this if the result length is still more than
        _keep_no_result , randomly selects _keep_no_results from the result list. The output can then be sent for insertion in the graph

    :return: A list of results which can directly be used for inserting into a graph
    _results: a result list which contains the sparql variables 'e' and 'p'.
                They can be of either left or right queries as the cell above
        _labels: a tuple with three strings, which depict the nomenclature of the resources to be pushed
        _direction: True -> one triple right; False -> one triple left
        _origin_node: the results variable only gives us one p and one e.
                Depending on the direction, this node will act as the other e to complete the triple
        _filter_properties: if True, only properties existing in properties whitelist will be pushed in.
        _filter_entities: if True, only entites belonging to a particular classes present in the whitelist will be pushed in.

    '''
    print "@pruning"
    temp_results = []
    # properties_count = {}
    results_list = []
    for result in _results[u'results'][u'bindings']:
        prop = result[u'p'][u'value']
        if _filter_properties:
            if not prop.split('/')[-1] in relevant_properties:
                continue
        results_list.append(result)
    if len(results_list) > 2000:
        results_list = random.sample(results_list,1000)
    print len(results_list)
    for result in results_list:
        # Parse the results into local variables (for readibility)
        prop = result[u'p'][u'value']
        ent = result[u'e'][u'value']
        # ent_type = result[u'type'][u'value']
        # print ent_type
        if _filter_literals:
            if nlutils.has_literal(ent):
                continue

        if _filter_properties:
            # Filter results based on important properties


            if not prop.split('/')[-1] in relevant_properties:
                continue
            ent_parent = dbp.get_most_specific_class(ent)
            try:
                if properties_count[ent_parent][prop.split('/')[-1]] > 1:
                    continue
                else:
                    properties_count[ent_parent][prop.split('/')[-1]] = properties_count[prop.split('/')[-1]] + 1
            except:
                try:
                    properties_count[ent_parent][prop.split('/')[-1]] = 1
                except:
                    properties_count[ent_parent] = {}

        if _filter_entities:
            # filter entities based on class
            if not [i for i in dbp.get_type_of_resource(ent) if i in relevent_entity_classes]:
                continue
        # Finally, insert, in a temporary list for random pruning
        temp_results.append(result)

    if (len(temp_results) > _keep_no_results):
        return random.sample(temp_results,_keep_no_results)
    print len(temp_results)
    return temp_results

def insert_triple_in_subgraph(G, _results, _labels, _direction, _origin_node, _filter_properties=True,
                              _filter_literals=True,_filter_entities = False):
    '''
        Function used to push the results of different queries into the subgraph.
        USAGE: only within the get_local_subgraph function.

        INPUTS:
        _subgraph: the subgraph object within which the triples are to be pushed
        _results: a result list which contains the sparql variables 'e' and 'p'.
                They can be of either left or right queries as the cell above
        _labels: a tuple with three strings, which depict the nomenclature of the resources to be pushed
        _direction: True -> one triple right; False -> one triple left
        _origin_node: the results variable only gives us one p and one e.
                Depending on the direction, this node will act as the other e to complete the triple
        _filter_properties: if True, only properties existing in properties whitelist will be pushed in.
        _filter_entities: if True, only entites belonging to a particular classes present in the whitelist will be pushed in.
    '''

    for result in _results:
        # Parse the results into local variables (for readibility)

        prop = result[u'p'][u'value']
        ent = result[u'e'][u'value']

        if _direction == True:
            # Right
            subgraph.insert(G=G, data=[(_labels[0], _origin_node), (_labels[1], prop), (_labels[2], ent)])

        elif _direction == False:
            # Left
            subgraph.insert(G=G, data=[(_labels[0], ent), (_labels[1], prop), (_labels[2], _origin_node)])


def get_local_subgraph(_uri):
    # Collecting required variables: DBpedia interface, and a new subgraph
    global dbp

    # Create a new graph
    G = nx.DiGraph()
    access = subgraph.accessGraph(G)

    ########### e ?p ?e (e_to_e_out and e_out) ###########
    start = time.clock()
    results = dbp.shoot_custom_query(one_triple_right % {'e': _uri})
    print "shooting custom query to get one triple right from the central entity e" , str(time.clock() - start)
    print "total number of entities in right of the central entity is e ", str(len(results))
    labels = ('e', 'e_to_e_out', 'e_out')

    # Insert results in subgraph
    print "inserting triples in right graph "
    start = time.clock()
    results = pruning(_results=results, _keep_no_results=10, _filter_properties=True, _filter_literals=True, _filter_entities=False)
    insert_triple_in_subgraph(G, _results=results,
                              _labels=labels, _direction=True,
                              _origin_node=_uri, _filter_properties=True)
    print "inserting the right triple took " , str(time.clock() - start)
    ########### ?e ?p e (e_in and e_in_to_e) ###########
    # raw_input("check for right")
    results = dbp.shoot_custom_query(one_triple_left % {'e': _uri})
    labels = ('e_in', 'e_in_to_e', 'e')
    print "total number of entity left of the central entity e is " , str(len(results))
    # Insert results in subgraph
    print "inserting into left graph "
    start = time.clock()
    results = pruning(_results=results, _keep_no_results=100, _filter_properties=True, _filter_literals=True,
                      _filter_entities=True)
    insert_triple_in_subgraph(G, _results=results,
                              _labels=labels, _direction=False,
                              _origin_node=_uri, _filter_properties=True)
    print "inserting triples for left of the central entity  took ", str(time.clock() - start)
    ########### e p eout . eout ?p ?e (e_out_to_e_out_out and e_out_out) ###########

    # Get all the eout nodes back from the subgraph.
    start = time.clock()
    e_outs = []
    op = access.return_outnodes('e')
    for x in op:
        for tup in x:
            print tup
            e_outs.append(tup[1].getUri())
    print "total time taken to retrive from subgraph is " , str(time.clock() - start)
    print "total number of entites retirved from subgraph which are right is " , str(len(op))

    labels = ('e_out', 'e_out_to_e_out_out', 'e_out_out')

    print "insert into e_out_to_e_out_out", str(len(e_outs))
    # raw_input("check !!")
    for e_out in e_outs:
        start = time.clock()
        results = dbp.shoot_custom_query(one_triple_right % {'e': e_out})
        print "time required to shoot query is " , str(time.clock() - start)
        # Insert results in subgraph
        results = pruning(_results=results, _keep_no_results=100, _filter_properties=True, _filter_literals=True,
                          _filter_entities=False)
        insert_triple_in_subgraph(G, _results=results,
                                  _labels=labels, _direction=True,
                                  _origin_node=e_out, _filter_properties=True)
        print "time required to shoot query is ", str(time.clock() - start)
        # print "done"

    ########### e p eout . ?e ?p eout  (e_out_in and e_out_in_to_e_out) ###########

    # Use the old e_outs variable
    labels = ('e_out_in', 'e_out_in_to_e_out', 'e_out')
    print "insert into e_out_in_to_e_out_out", str(len(e_outs))
    for e_out in e_outs:
        results = dbp.shoot_custom_query(one_triple_left % {'e': e_out})

        # Insert results in subgraph
        results = pruning(_results=results, _keep_no_results=20, _filter_properties=True, _filter_literals=True,
                          _filter_entities=False)
        insert_triple_in_subgraph(G, _results=results,
                                  _labels=labels, _direction=False,
                                  _origin_node=e_out, _filter_properties=True)

    ########### ?e ?p ein . ein p e  (e_in_in and e_in_in_to_e_in) ###########

    # Get all the ein nodes back from subgraph
    e_ins = []
    op = access.return_innodes('e')
    for x in op:
        for tup in x:
            e_ins.append(tup[0].getUri())

    labels = ('e_in_in', 'e_in_in_to_e_in', 'e_in')

    print "insert into sub sub sub graph" , str(len(e_ins))
    for e_in in e_ins:
        results = dbp.shoot_custom_query(one_triple_left % {'e': e_in})

        # Insert results in subgraph
        results = pruning(_results=results, _keep_no_results=20, _filter_properties=True, _filter_literals=True,
                          _filter_entities=False)
        insert_triple_in_subgraph(G, _results=results,
                                  _labels=labels, _direction=False,
                                  _origin_node=e_in, _filter_properties=True)
        print "done"
    ########### ein ?p ?e . ein p e  (e_in_to_e_in_out and e_in_out) ###########

    # Use the old e_ins variable
    labels = ('e_in', 'e_in_to_e_in_out', 'e_in_out')
    print "insert into sub sub sub sub graph", str(len(e_ins))
    for e_in in e_ins:
        results = dbp.shoot_custom_query(one_triple_right % {'e': e_in})

        # Insert results in subgraph
        results = pruning(_results=results, _keep_no_results=10, _filter_properties=True, _filter_literals=True,
                          _filter_entities=False)
        insert_triple_in_subgraph(G, _results=results,
                                  _labels=labels, _direction=True,
                                  _origin_node=e_in, _filter_properties=True)
        print "done"

    # Pushed all the six kind of nodes in the subgraph. Done!
    return G


def fill_specific_template(_template_id, _mapping,_debug=False):
    '''
        Function to fill a specific template.
        Given the template ID, it is expected to fetch the template from the set
            and juxtapose the mapping on the template.

        Moreover, it also has certain functionalities that help the future generation of verbalizings.
             -> Returns the answer of the query, and the answer type
             -> In some templates, it also fetches the intermediate hidden variable and it's types too.

        -> create copy of template from the list
        -> get the needed metadata
        -> push it in the list
    '''

    global sparql, templates, outputfile

    # Create a copy of the template
    template = [x for x in templates if x['id'] == _template_id][0]
    template = copy.copy(template)

    # From the template, make a rigid query using mappings
    try:
        template['query'] = template['template'] % _mapping
    except KeyError:
        print "fill_specific_template: ERROR. Mapping does not match."
        return False

    # Include the mapping within the template object
    template['mapping'] = _mapping

    # Get the Answer of the query
    # get_answer now returns a dictionary with appropriate variable bindings.
    template['answer'] = dbp.get_answer(template['query'])

    # Get the most specific type of the answers.
    '''
        ATTENTION: This can create major problems in the future.
        We are assuming that the most specific type of one 'answer' would be the most specific type of all answers.
        In cases where answers are like Bareilly (City), Uttar Pradesh (State) and India (Country),
            the SPARQL and NLQuestion would not be the same.
            (We might expect all in the answers, but the question would put a domain restriction on answer.)

        @TODO: attend to this!
    '''
    template['answer_type'] = {}
    for variable in template['answer']:
        template['answer_type'][variable] = dbp.get_most_specific_class(template['answer'][variable][0])
        template['mapping'][variable] = template['answer'][variable][0]

    mapping_type = {}
    for key in template['mapping']:
        mapping_type[key] = dbp.get_type_of_resource(template['mapping'][key],_filter_dbpedia = True)

    template['mapping_type'] = mapping_type
    if _debug:
        pprint(template)
    # Push it onto the SPARQL List
    # perodic write in file.
    # @TODO: instead of file use a database.
    try:
        sparqls[_template_id].append(template)
        print len(sparqls[_template_id])
        if len(sparqls[_template_id]) > 100000:
            print "in if condition"
            print "tempalte id is ", str(_template_id)
            with open('output/template%s.txt' % str(_template_id), "a+") as out:
                pprint(sparqls[_template_id], stream=out)
            with open('output/template%s.json' % str(_template_id), "a+") as out:
                json.dump(sparqls[_template_id], out)
            sparqls[_template_id] = []
    except:
        print traceback.print_exc()
        sparqls[_template_id] = [template]

    return True


def fill_templates(_graph, _uri):
    '''
        This function is programmed to traverse through the Subgraph and create mappings for templates

        Per template traverse the graph, and pick out the needed stuff in local variables
    '''

    global dbp

    access = subgraph.accessGraph(_graph)


    '''
        Template #3:
            SELECT DISTINCT ?uri WHERE { <%(e_in_in)s> <%(e_in_in_to_e_in)s> ?x . ?x <%(e_in_to_e)s> ?uri }
        Find e_in and e_in_to_e.
    '''

    # Query the graph for innode to e and relevant properties
    op = access.return_innodes('e')
    print "length of innodes is " , str(len(op))
    counter_template3 = 0
    # Create a list of all these (e_in, e_in_to_e)
    one_triple_left_map = {triple[0].getUri(): triple[2]['object'].getUri() for triple in op[0]}
    pprint(one_triple_left)

    # Collect all e_in_in and e_in_in_to_e_in
    op = access.return_innodes('e_in')
    print "length of innodes is ", str(len(op))
    counter_template1 = 0

    # This 'op' has the e_in_in and the prop for all e_in's. We now need to map one to the other.
    for list_of_triples in op:

        # Some triple are simply empty. Ignore them.
        if len(list_of_triples) == 0:
            continue

        ### Mapping e_in_in's to relevant e_in's ###

        # Pick one triple from the list.
        e_in = list_of_triples[0][1].getUri()
        e_in_to_e = one_triple_left_map[e_in]
        # Find the relevant property from the map

        # Given this information, lets create mappings of template three
        for triple in list_of_triples:

            # Making the variables explicit (for the sake of readability)
            e_in_in = triple[0].getUri()
            e_in_in_to_e_in = triple[2]['object'].getUri()

            # Create a mapping (in keeping with the templates' placeholder names)
            mapping = {'e_in_in': e_in_in, 'e_in_in_to_e_in': e_in_in_to_e_in, 'e_in_to_e': e_in_to_e, 'e_in': e_in}
            mapping_type = {}
            # Throw it to a function who will put it in the list with appropriate bookkeeping
            try:
                fill_specific_template(_template_id=3, _mapping=mapping)
                counter_template3 = counter_template3 + 1
                print str(counter_template3), "tempalte3"
                if counter_template3 > 500:
                    break
                    #                     break
            except:
                print "check error stack"
                traceback.print_exc()
                continue


# break

'''
    Testing the ability to create subgraph given a URI
    Testing the ability to generate sparql templates
'''
sparqls = {}
dbp = db_interface.DBPedia(_verbose=True)
def generate_answer(_uri, dbp):
    uri = _uri

    # Generate the local subgraph
    graph = get_local_subgraph(uri)
    print "the graph is completed"
    # Generate SPARQLS based on subgraph
    fill_templates(graph, _uri=uri)
    print "done with one entity"

for entity in list_of_entities:
    generate_answer(entity,dbp)

for key in sparqls:
    with open('output/template%d.txt' % key, 'a+') as out:
        pprint(sparqls[key], stream=out)
for key in sparqls:
    f = open('output/template%s.json' % key, 'a+')
    json.dump(sparqls[key], f)
    f.close()

# for i in range(1, len(sparqls)):
#     with open('output/template%d.txt' % i, 'a+') as out:
#         pprint(sparqls[i], stream=out)
# for i in range(1, len(sparqls)):
#     f = open('output/template%s.json' % i, 'a+')
#     json.dump(sparqls[i], f)
#     f.close()
print "DONE"