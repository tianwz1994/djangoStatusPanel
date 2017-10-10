# -*- coding: utf-8 -*-
import json
import pika
import time
from datetime import datetime
from . import qosDb
from .threadMqConsumers import MqConsumers

timeStampFormat="%Y%m%d%H%M%S"
agentProtocolVersion=1

# send message "ServerStarted" to "qos.service" queue
# (no exception handling)
# routingKeys is list [routingKey]
# routingKey "agent" causes re-registration of all agents
# routingKey "agent-someAgentKey" causes re-registration of single agent
def sendRegisterMessage(server,routingKeys):
    
    exchangeName="qos.service"
    queueName="heartbeatService"
    msgHeaders={"__TypeId__":"com.tecomgroup.qos.communication.message.ServerStarted"}
    msgBody={"originName":None,"serverName":""}
    
    serverConfig = server.getConfigObject()
    errors=[]
    mqConf = getMqConf(serverConfig['mq'], server.name, errors)

    # raise exception only if all mq's are down, so message sending is impossible
    if mqConf is None:
        raise Exception("sendRegisterMessage error: " + str(errors))

    connection=pika.BlockingConnection(pika.URLParameters(mqConf['amqpUrl']))
    channel = connection.channel()

    channel.exchange_declare(exchange=exchangeName, exchange_type='topic', durable=True)
    channel.queue_declare(queue=queueName, durable=True,arguments={'x-message-ttl':1800000})
    channel.queue_bind(queue=queueName, exchange=exchangeName, routing_key="server.agent.register")

    for key in routingKeys:
        channel.basic_publish(
            exchange=exchangeName,
            routing_key=key,
            properties=pika.BasicProperties(
                delivery_mode=2,  # make message persistent
                content_type='application/json',
                content_encoding='UTF-8',
                priority=0,
                expiration="86400000",
                headers=msgHeaders),
            body=json.dumps(msgBody).encode('UTF-8')
        )
    connection.close()



def sendHeartBeatTasks(mqAmqpConnection,tasksToPoll,sendToExchange,serverMode=False):
    if not mqAmqpConnection:
        return ['Соединение с RabbitMQ не установлено']
    
    errors=[]

    channel = mqAmqpConnection.channel()

    try:
        channel.exchange_declare(exchange=sendToExchange, exchange_type='topic', durable=True)
    except Exception as e:
        errors+= [str(e)]
        return errors

    for taskKey, task in tasksToPoll.items():
        
        msgRoutingKey=task['agentKey']        
        if serverMode:
            # process only heartbeat tasks
            if task.get('module',None)!='heartbeat':
                continue
            # process only enabled tasks
            if not task.get('enabled',False):
                continue
            # skip sending error tasks from server
            if task.get('error',False):
                continue
            timeStamp=(datetime.utcnow()).strftime(timeStampFormat)
            msgBody={"config":task['config'],
                     "format":task.get('format',None)
                    }
        else:
            msgBody=task.get('value',"")
            timeStamp=task['timeStamp']

        msgHeaders={'key':taskKey,'timestamp':timeStamp,'unit':task['unit'],
                    'protocolversion':agentProtocolVersion}

        if "error" in task.keys():
            msgHeaders['error']=task['error']

        channel.basic_publish(
            exchange=sendToExchange,
            routing_key=msgRoutingKey,
            properties=pika.BasicProperties(
                delivery_mode=2,  # make message persistent
                content_type='application/json',
                content_encoding='UTF-8',
                priority=0,
                expiration="86400000",
                headers=msgHeaders),
            body=json.dumps(msgBody).encode('UTF-8')
        )
    return errors


def receiveHeartBeatTasks(mqAmqpConnection,tasksToPoll,receiveFromQueue,serverMode=False):

    if not mqAmqpConnection:
        return ['Соединение с RabbitMQ не установлено']
    vErrors=[]

    channel = mqAmqpConnection.channel()

    try:
        channel.queue_declare(queue=receiveFromQueue, durable=True,arguments={'x-message-ttl':1800000})
    except Exception as e:
        vErrors+= [str(e)]
        return vErrors

    try:
        channel.exchange_declare(exchange=receiveFromQueue, exchange_type='topic', durable=True)
    except Exception as e:
        vErrors+= [str(e)]
        return vErrors

    try:
        channel.queue_bind(queue=receiveFromQueue, exchange=receiveFromQueue, routing_key="#")
    except Exception as e:
        vErrors+= [str(e)]
        return vErrors

    mqMessages = []
    while True:
        # connect and check errors (amqp)
        getOk = None
        try:
            getOk, *mqMessage = channel.basic_get(receiveFromQueue, no_ack=True)
        except Exception as e:
            errStr = str(e)
            if errStr not in vErrors:
                vErrors += [errStr]
            continue
        if getOk:
            mqMessage=[getOk]+mqMessage
            if mqMessage[1].content_type != 'application/json':
                errStr = "Неверный тип данных " + mqMessage[0].content_type
                if errStr not in vErrors:
                    vErrors += [errStr]
                continue
            mqMessages += [mqMessage]
        else:
            break
    # endwhile messages in rabbit queue            

    # now we have list of mqMessages
    for msg in mqMessages:

        try:
            headers = msg[1].headers
            taskKey=headers['key']
            taskUnit=headers['unit']
        except Exception as e:
            errStr = "Ошибка обработки сообщения: неверный заголовок."
            if errStr not in vErrors:
                vErrors += [errStr]
            continue

        # parse message payload
        try:
            msgBody = json.loads((msg[2]).decode('utf-8'))
            # msgBody['value']=777
        except Exception as e:
            errStr = "Ошибка обработки сообщения: неверное содержимое."
            if errStr not in vErrors:
                vErrors += [errStr]
            continue
        
        if serverMode:            
            if headers.get('protocolversion',0) < agentProtocolVersion:
                errStr = ('Версия heartbeatAgent устарела. Обновите heartbeatAgent на '+msg[0].routing_key)
                if errStr not in vErrors:
                    vErrors += [errStr]
                continue

            if taskKey not in tasksToPoll.keys():
                errStr = ('Ошибка обработки сообщения: неверный ключ '+taskKey)
                if errStr not in vErrors:
                    vErrors += [errStr]
                continue

            try:
                stringTimeStamp=headers['timestamp']
                taskTimeStamp=datetime.strptime(stringTimeStamp, timeStampFormat)
                tasksToPoll[taskKey]['timeStamp']=taskTimeStamp
            except Exception as e:
                errStr = "Ошибка обработки сообщения: неверная метка времени."
                if errStr not in vErrors:
                    vErrors += [errStr]
                continue

            error=headers.get('error',None)

            # not set value tag on empty string receive
            if msgBody!='':
                tasksToPoll[taskKey]['value']=msgBody
            else:
                if error is None:
                    error="значение не вычислено"

            tasksToPoll[taskKey]['unit']=taskUnit
            if error is not None:
                tasksToPoll[taskKey]['error']=error
        else:
            tasksToPoll[taskKey]={'module':'heartbeat','agentKey':msg[0].routing_key,
                                  'unit':taskUnit,'config':msgBody['config'],
                                  'format':msgBody['format']}
    # endfor messages in current request
    return vErrors

def formatErrors(errors, serverName, pollName):
    return [{
        'id': serverName + '.' + pollName + '.' + str(i),
        'name': pollName + ": " + text,
        'error': text,
        'style': 'rem',
        # this is error message from server, not an actual task
        'servertask':True} 
        for i, text in enumerate(errors)]


# dbConfig -> (dbConnection,tasksToPoll)
# get db connection for later use and query list of tasks from db
def pollDb(dbConfig, serverName, vServerErrors):
    # poll database
    pollName = "Database"
    errors = []
    dbConnections = []

    # check all db in dbconf
    for dbConf in dbConfig:
        try:
            if dbConf.get('server','')!='':
                curConnection = qosDb.getDbConnection(dbConf)
            else:
                continue

        except Exception as e:
            errors += [str(e)]
            continue
        else:
            dbConnections += [curConnection]

    tasksToPoll = None
    dbConnection = None

    if dbConnections:
        # close all connections but first
        for i in range(1, len(dbConnections)):
            dbConnections[i].close()
        # use first connection in later tasks
        dbConnection = dbConnections[0]

        e, tmp = qosDb.getTasks(dbConnection)
        if e is None:
            tasksToPoll = tmp
        else:
            errors += [e]
    # endif
    vServerErrors += formatErrors(errors, serverName, pollName)
    tasksToPoll = {} if tasksToPoll is None else tasksToPoll
    return (dbConnection, tasksToPoll)


# test all rabbitMQ configs and return first working to mqconf
# mqConfig=[mqConf] -> mqConf (select first working mqconf)
def getMqConf(mqConfig,serverName,vServerErrors):
    pollName = "CheckRabbitMq"
    errors = []

    # mqAmqpConnection if first working mq was found and res is corresponding mqConf
    res=None
    for mqConf in mqConfig:
        try:
            con = pika.BlockingConnection(pika.URLParameters(mqConf['amqpUrl']))
        except Exception as e:
            errors += [str(e)]
        else:
            if res is None:
                # use first working connection in later tasks
                res=mqConf
            #close amqplink
            if con.is_open:
                con.close()
    # endfor

    vServerErrors += formatErrors(errors, serverName, pollName)
    return res


def pollMQ(serverName, mqConsumerId, vServerErrors, vTasksToPoll):
    pollName = "RabbitMQ"
    errors = set()

    try:
        mqMessages = MqConsumers.popConsumerMessages(mqConsumerId)
    except Exception as e:
        errors.add(str(e))
        vServerErrors += formatErrors(errors, serverName, pollName)
        return

    # print("**************************",mqConsumerId)
    # print(mqMessages)

    # now we have list of mqMessages
    for msg in mqMessages:
        if type(msg)!=tuple or len(msg)!=3:
            errors.add("RabbitMQ вернул недопустимые данные")
            continue

        # unpack tuple
        mMetaData, mProperties, mData=msg      

        try:
            mHeaders=mProperties.headers
            if mProperties.content_type != 'application/json':
                errors.add("Неверный тип данных в сообщении RabbitMQ" + mProperties)
                continue
        except Exception as e:
            errors.add(e)
            continue

        msgType = ""
        try:
            msgType = mHeaders['__TypeId__']
        except Exception as e:
            errors.add("Ошибка обработки сообщения: нет информации о типе.")
            continue

        # parse message payload
        try:
            mData = json.loads((mData).decode('utf-8'))
            taskKey = mData['taskKey']

            if taskKey not in vTasksToPoll.keys():
                errors.add("Задача " + taskKey + " не зарегистрирована в БД")
                continue

            if msgType == 'com.tecomgroup.qos.communication.message.ResultMessage':

                taskResults = mData['results']
                for tr in taskResults:
                    # if result has any parameters - store in timeStamp vTasksToPoll
                    if len(tr['parameters'].keys()) > 0:
                        vTasksToPoll[taskKey]['timeStamp'] = datetime.strptime(tr['resultDateTime'], timeStampFormat)

            elif msgType == 'com.tecomgroup.qos.communication.message.TSStructureResultMessage':
                if len(mData['TSStructure']) > 0:
                    vTasksToPoll[taskKey]['timeStamp'] = datetime.strptime(mData['timestamp'], timeStampFormat)
            else:
                errors.add("Неизвестный тип сообщения: " + msgType)
                continue

        except Exception as e:
            errors.add(str(e))
            continue

    # endfor

    vServerErrors += formatErrors(errors, serverName, pollName)


# send heartbeat tasks request to rabbitmq exchange
def subSendHeartBeatTasks(mqConf,serverName,tasksToPoll,serverErrors):
    con=pika.BlockingConnection(pika.URLParameters(mqConf['amqpUrl']))
    errors=sendHeartBeatTasks(con,tasksToPoll,mqConf['heartbeatAgentRequest'],True)
    serverErrors += formatErrors(errors, serverName, "hbSender")
    con.close()


# receive heartbeat tasks request from rabbitmq queue
def subReceiveHeartBeatTasks(mqConf,serverName,tasksToPoll,serverErrors,oldTasks):
    con=pika.BlockingConnection(pika.URLParameters(mqConf['amqpUrl']))
    errors=receiveHeartBeatTasks(con,tasksToPoll,mqConf['heartbeatAgentReply'],True)
    serverErrors += formatErrors(errors, serverName, "hbReceiver")
    con.close()

    # process composite heartbeat tasks decomposing
    # these tasks returns >1 values in dictionary like 
    # {key1: value1, key2: value2 ....}
    tasksToAdd={}
    tasksToRemove=set()
    for taskKey,task in tasksToPoll.items():
        if task.get("module",None)=='heartbeat' and task.get('enabled',False):

            if "value" in task.keys():
                # hb value received and this is composite task
                # decompose composite task to some simple tasks
                value=task['value']
                if type(value)==dict:
                    for resultKey,resultValue in value.items():
                        childTaskKey=taskKey+"."+resultKey
                        childTask=task.copy()
                        # tasks with "parentkey" property set are the children tasks
                        # ex. cpu load of core #1 #2 ... #24 are the children tasks of "cpu load"
                        childTask["parentkey"]=taskKey
                        childTask["value"]=resultValue
                        tasksToAdd.update({childTaskKey:childTask})
                        tasksToRemove.add(taskKey)
            else:
                # hb value not received
                # check if there are early decomposed (children) tasks in oldTasks with 
                # parentkey == current task
                oldChildrenTasks={k:v for k,v in oldTasks.items() 
                                        if v.get("parentkey",None)==taskKey}
                if oldChildrenTasks:
                    # remove this composite task without value
                    tasksToRemove.add(taskKey)
                    
                    newChildrenTasks={k:task.copy() for k in oldChildrenTasks.keys()}
                    # add some parameters from oldChildrenTass to NewChildrenTasks
                    useOldParameters(newChildrenTasks,oldChildrenTasks)
                    # add early decomposed (children) tasks instead
                    tasksToAdd.update(newChildrenTasks)
                    # tasksToAdd.update(oldChildrenTasks)

    # actually do add and remove for composite tasks
    for t2r in tasksToRemove:
        tasksToPoll.pop(t2r)
    tasksToPoll.update(tasksToAdd)


# move some parameters from previous poll if they are absent in current poll
def useOldParameters(vTasksToPoll, oldTasks):
    for taskKey, task in vTasksToPoll.items():
        if taskKey in oldTasks.keys():
            if 'timeStamp' not in task.keys() and ('timeStamp' in oldTasks[taskKey].keys()):
                task['timeStamp'] = oldTasks[taskKey]['timeStamp']
                
                # if results not received - then prolongate old errors, else no
                if 'error' not in task.keys() and ('error' in oldTasks[taskKey].keys()):
                    task['error'] = oldTasks[taskKey]['error']

            if 'value' not in task.keys() and ('value' in oldTasks[taskKey].keys()):
                task['value'] = oldTasks[taskKey]['value']
            if 'unit' not in task.keys() and ('unit' in oldTasks[taskKey].keys()):
                task['unit'] = oldTasks[taskKey]['unit']
            if 'parentkey' not in task.keys() and ('parentkey' in oldTasks[taskKey].keys()):
                task['parentkey'] = oldTasks[taskKey]['parentkey']


def markTasks(tasksToPoll, oldTasks, pollStartTimeStamp, appStartTimeStamp, pollingPeriodSec):

    # extended error check and task markup for heartbeat tasks.
    def markHeartBeatTask(task):

        # check that task received a value
        if task.get('value',None) is None:
            task['error']="Значение не вычислено"
            return

        # check expected results count==actual count (if specified in settings)
        expResCount=task['config'].get('resultcount',None)
        if expResCount is not None:
            # user-specified key for item, like "cpu", "loadAverage" etc
            itemKey=task['itemKey']
            agentName=task['agentName']
            isTaskToCount=lambda t: \
                t.get('itemKey',None)==itemKey and \
                t.get('agentName',None)==agentName and \
                t.get('enabled',True)
            factResCount=sum([1 for t in tasksToPoll.values() if isTaskToCount(t) ])
            if expResCount!=factResCount:
                for t in tasksToPoll.values():
                    if isTaskToCount(t):
                        t['error']="в настройках задано результатов: "+str(expResCount)+" фактически получено: "+str(factResCount)
                return
            #end if
        #end if
    # end sub

    # remove all markups if exists
    for taskKey, task in tasksToPoll.items():
        task.pop('style', None)

    # common task markup. status of data recieve
    for taskKey, task in tasksToPoll.items():
        if not task.get('enabled',True):
            task['style'] = 'ign'
        else:
            if task.get('timeStamp', None) is None:
                # if task is absent in previous poll - then not mark it as error
                if taskKey in oldTasks.keys():
                    task['error'] = "задача не присылает данные"
                else:
                    task['style'] = 'ign'
        # endif task enabled
    # endfor

    noDataForLongTimeError='задача не присылает данные длительное время'
    # common task markup. idle time
    for task in tasksToPoll.values():
        if task.get('style',None) is None:
            if "timeStamp" in task.keys():
                idleTime = datetime.utcnow() - task['timeStamp']
                idleTime = idleTime.days * 86400 + idleTime.seconds

                if abs(idleTime) > \
                        3 * max(task['period'], pollingPeriodSec):
                    if task.get('error',None) is None:
                        task['error'] = noDataForLongTimeError
    #end for

    #additional markup for heartbeat tasks. Data value, triggers
    for task in tasksToPoll.values():
        # task not received any markup or error in standart markup process
        # so, make extended check
        if (task.get('module',None)=='heartbeat') and \
                (task.get('style',None) is None) and \
                (task.get('error',noDataForLongTimeError)==noDataForLongTimeError):
            # if no error or noDataForLongTimeError
            markHeartBeatTask(task)

    # display error style in task caption
    for taskKey, task in tasksToPoll.items():
        error=task.get('error',None)
        if (error is not None):
            task['style'] = 'rem'

# create box for every agent (controlblock)
# agents like {agent:[tasks]}
# taskstopoll -> pollResult
def makePollResult(tasksToPoll, serverName, serverErrors):
    pollResult=[]
    agents = {}
    agentHasErrors = set()
    if tasksToPoll is not None:
        for taskKey, task in tasksToPoll.items():
            # boxName is used for box caption
            boxName = task['agentName']

            if boxName in agents.keys():
                curTasks = agents[boxName]
            else:
                curTasks = []
                agents[boxName] = curTasks

            taskData = {"id": serverName + '.' + taskKey}

            # filter parameters to write from tasksToPoll to pollResult
            taskData.update({key:task[key] 
                for key in 
                    #agentName not included - because it already presents in box name
                    ["style","agentKey","timeStamp","enabled","unit","value","error","itemName"]
                if key in task.keys()})

            if task.get('style', None) == 'rem':
                agentHasErrors.add(boxName)

            # processing errors for tasks without timestamp and tasks with old timestamp
            # taskStyle = task.get('style', None)
            # if taskStyle is not None:
            #     taskData.update({"style": taskStyle})
            #     if taskStyle == 'rem':
            #         agentHasErrors.add(boxName)

            curTasks += [taskData]

    # add box with server errors to pollresult
    if len(serverErrors) > 0:
        pollResult += [{
            "id": serverName,
            "name": serverName,
            "pollServer": serverName,
            "error": "Ошибки при опросе сервера " + serverName,
            "data": serverErrors,
            }]

    # add agents with errors to pollresult
    resultWithErrors = [{
        "id": serverName + '.' + key,
        "name": key,
        "error": key + " : Ошибки в одной или нескольких задачах",
        "data": taskData,
        "pollServer": serverName}
        for key, taskData in agents.items()
        if key in agentHasErrors]
    pollResult += resultWithErrors

    # add agents without errors to pollresult
    resultNoErrors = [{"id": serverName + '.' + key,
                       "name": key,
                       "data": taskData,
                       "pollServer": serverName}
                      for key, taskData in agents.items()
                      if key not in agentHasErrors]
    pollResult += resultNoErrors

    # calc errors percent in pollresult ("no error" tasks/"error" tasks condition in percent)
    for poll in pollResult:
        if "error" in poll:
            count = len(poll['data'])
            if count > 0:
                errCount = sum([record.get("style", None) ==
                                "rem" for record in poll['data']])
                # print (errCount)
                poll['progress'] = int(100 * errCount / count)
                if poll['pollServer'] == poll['name']:
                    # box with common server errors
                    errHead = poll['pollServer']
                else:
                    # box with some host errors and tasks
                    errHead = poll['pollServer'] + " : " + poll['name']
                poll['error'] = "{0} : Обнаружено ошибок: {1} из {2}".format(
                    errHead, errCount, count)

    return pollResult


def pollResultSort(vPollResult):
    # sort pollresults like servername & boxname, make boxes with errors first
    # also look views.py/makeBoxCaption for box caption rule
    vPollResult.sort(key=lambda v: ("0" if "error" in v.keys() else "1") + v['pollServer']+" "+v['name'])


def qosGuiAlarm(tasksToPoll, oldTasks, serverName, serverDb, mqConf, opt, vServerErrors):
    # dublicate errors "no task data" to qos server gui
    pollName = "QosGuiAlarm"
    errors = []

    # add alarmPublishStatus from prev poll if absent
    for taskKey, task in tasksToPoll.items():
        if taskKey in oldTasks.keys():
            if ('alarmPublishStatus' not in tasksToPoll.keys()) and \
                    ('alarmPublishStatus' in oldTasks[taskKey].keys()):
                task['alarmPublishStatus'] = oldTasks[taskKey]['alarmPublishStatus']

    # get originatorID - service integer number to send alarm
    e, originatorId = qosDb.getOriginatorIdForAlertType(
        dbConnection=serverDb, alertType=opt['qosAlertType'])
    if e is None:
        # send alarms to main GUI interface of server
        # originatorID is the service integer number to send alarm
        # agents like
        # {akentkey:[{"id":task_serv_id,"taskKey":taskKey,"name":taskText,"style":"rem"}]}  
        con=pika.BlockingConnection(pika.URLParameters(mqConf['amqpUrl']))
        channel = con.channel()
        for taskKey, task in tasksToPoll.items():
            
            if task.get('module',None)=='heartbeat':
                continue

            action = "ACTIVATE" if task.get('style', None) == 'rem' else "CLEAR"

            # 0 - not published
            # 1 - published activate
            # 2 - published clear
            alarmPublishStatus = tasksToPoll[taskKey].get('alarmPublishStatus', 0)
            needPublish = False

            if action == "ACTIVATE":
                if alarmPublishStatus != 1:
                    needPublish = True
                    alarmPublishStatus = 1

            if action == "CLEAR":
                if alarmPublishStatus != 2:
                    needPublish = True
                    alarmPublishStatus = 2

            if needPublish:
                tasksToPoll[taskKey]['alarmPublishStatus'] = alarmPublishStatus
                # print('publish alarm')
                channel.basic_publish(
                    exchange='qos.alert',
                    routing_key='',
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # make message persistent
                        content_type='application/json',
                        content_encoding='UTF-8',
                        priority=0,
                        expiration="86400000",
                        headers={
                            '__TypeId__': 'com.tecomgroup.qos.communication.message.AlertMessage'}),
                    body="""{
                        "originName":null,
                        "action":"{action}",
                        "alert":{
                            "alertType":{
                                "name":"{alerttype}",
                                "probableCause":null,
                                "displayName":null,
                                "displayTemplate":null,
                                "description":null},
                            "perceivedSeverity":"{ceverity}",
                            "specificReason":"NONE",
                            "settings":"",
                            "context":null,
                            "indicationType":null,
                            "dateTime":{time},
                            "source":{"displayName":null,
                                "key":"{taskkey}",
                                "type":"TASK"},
                            "originatorID":{originatorid},
                            "originatorName":"123",
                            "detectionValue":0,
                            "thresholdValue":0
                        }}"""
                    .replace("{action}", action)
                    .replace("{alerttype}", opt['qosAlertType'])
                    .replace("{ceverity}", opt['qosSeverity'])
                    .replace("{time}", str(int(time.time()) * 1000))
                    .replace("{taskkey}", taskKey)
                    .replace("{originatorid}", str(int(originatorId)))
                )
        con.close()
        #endif e is none
    else:
        errors += [e]

    vServerErrors += formatErrors(errors, serverName, pollName)
