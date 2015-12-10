from datetime import datetime
import time
import importlib
import json
from uuid import uuid4
from copy import copy
import urllib

from pyramid.view import view_config

from nupic.frameworks.opf.modelfactory import ModelFactory
from nupic.algorithms import anomaly_likelihood

models = {}

@view_config(route_name='reset', renderer='json')
def reset(request):
    guid = request.matchdict['guid']
    has_model = guid in models
    if has_model:
        print "resetting model", guid
        models[guid]['model'].resetSequenceStates()
        models[guid]['seen'] = 0
        models[guid]['last'] = None
        models[guid]['alh'] = anomaly_likelihood.AnomalyLikelihood()
    else:
        request.response.status = 404
        return no_model_error()
    return {'success': has_model, 'guid': guid}


def du(unix):
    return datetime.utcfromtimestamp(float(unix))


def dt_to_unix(dt):
    return int(time.mktime(datetime.now().timetuple()))


def no_model_error():
    return {'error': 'No such model'}


def serialize_result(time_fieldname, result):
    result.rawInput[time_fieldname] = dt_to_unix(result.rawInput[time_fieldname])
    out = dict(
        predictionNumber=result.predictionNumber,
        rawInput=result.rawInput,
        sensorInput=dict(
            dataRow=result.sensorInput.dataRow,
            dataDict=result.rawInput,
            dataEncodings=[map(int, list(l)) for l in result.sensorInput.dataEncodings],
            sequenceReset=int(result.sensorInput.sequenceReset),
            category=result.sensorInput.category
        ),
        inferences=result.inferences,
        metrics=result.metrics,
        predictedFieldIdx=result.predictedFieldIdx,
        predictedFieldName=result.predictedFieldName,
        classifierInput=dict(
            dataRow=result.classifierInput.dataRow,
            bucketIndex=result.classifierInput.bucketIndex
        )
    )
    return out


def find_temporal_field(model_params):
    encoders = model_params['modelParams']['sensorParams']['encoders']
    tfield = None
    for name, encoder in encoders.iteritems():
        if encoder is not None and encoder['type'] == 'DateEncoder':
            return encoder['fieldname']


@view_config(route_name='models', renderer='json', request_method='PUT')
def run(request):
    guid = request.matchdict['guid']
    has_model = guid in models
    if not has_model:
        request.response.status = 404
        return no_model_error()
    print guid, '<-', request.json_body
    data = {k: float(v) for k, v in request.json_body.items()}
    model = models[guid]
    time_fieldname = model['tfield']
    if model['last'] and (data[time_fieldname] < model['last'][time_fieldname]):
        request.response.status = 400
        return {'error': 'Cannot run old data'}
    model['last'] = copy(data)
    # turn the timestamp field into a datetime obj
    data[time_fieldname] = du(data[time_fieldname])
    # model = model['model']
    resultObject = model['model'].run(data)
    anomaly_score = resultObject.inferences["anomalyScore"]
    responseObject = serialize_result(time_fieldname, resultObject)
    responseObject['anomalyLikelihood'] = model['alh'].anomalyProbability(data[model['pfield']], anomaly_score, data[time_fieldname])
    return responseObject


@view_config(route_name='models', renderer='json', request_method='DELETE')
def model_delete(request):
    guid = request.matchdict['guid']
    has_model = guid in models
    if not has_model:
        request.response.status = 404
        return no_model_error()
    else:
        print "Deleting model", guid
        del models[guid]
    return {'success': has_model, 'guid': guid}


@view_config(route_name='models', renderer='json', request_method='GET')
def model_get(request):
    guid = request.matchdict['guid']
    has_model = guid in models
    if not has_model:
        request.response.status = 404
        return no_model_error()
    else:
        return serialize_model(guid)


def serialize_model(guid):
    data = models[guid]
    return {
        'guid': guid,
        'predicted_field': data['pfield'],
        'params': data['params'],
        'last': data['last'],
        'seen': data['seen']
    }


@view_config(route_name='model_create', renderer='json', request_method='GET')
def model_list(request):
    return [serialize_model(guid) for guid in models]


@view_config(route_name='model_create', renderer='json', request_method='POST')
def model_create(request):
    guid = str(uuid4())
    predicted_field = None
    try:
        params = request.json_body
    except ValueError:
        params = None

    if params:
        if 'guid' in params:
            guid = urllib.quote_plus(params['guid'])
            if guid in models.keys():
                request.response.status = 409
                return {'error': 'The guid "' + guid + '" is not unique.'}
        if 'modelParams' not in params:
            request.response.status = 400
            return {'error': 'POST body must include JSON with a modelParams value.'}
        if 'predictedField' in params:
            predicted_field = params['predictedField']
        params = params['modelParams']
        msg = 'Used provided model parameters'
    else:
        params = importlib.import_module('model_params.model_params').MODEL_PARAMS['modelConfig']
        msg = 'Using default parameters, timestamp is field c0 and input and predictedField is c1'
        predicted_field = 'c1'
    model = ModelFactory.create(params)
    if predicted_field is not None:
        print "Enabled predicted field: {0}".format(predicted_field)
        model.enableInference({'predictedField': predicted_field})
    else:
        print "No predicted field enabled."
    models[guid] = {
        'model': model,
        'pfield': predicted_field,
        'params': params,
        'seen': 0,
        'last': None,
        'alh': anomaly_likelihood.AnomalyLikelihood(),
        'tfield': find_temporal_field(params)
    }
    print "Made model", guid
    return {'guid': guid, 'params': params, 'predicted_field': predicted_field, 'info': msg}
    
