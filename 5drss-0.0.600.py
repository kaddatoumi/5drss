#!/usr/bin/python3
import copy
import ipaddress
import os
from os import name, tcgetpgrp
import re
import sys
from prettytable import PrettyTable, ALL
import weakref #weak ref, only way to avoid issues with circular reference
import enum
import argparse
from collections import deque
import pathlib
from pathlib import Path
import xlsxwriter

#batch use: ls ../5health/ | grep .conf | cut -d "_" -f1 | uniq | while read i; do ./5drss-0.0.404.py -b ../5health/${i}_bigip_base.conf -t ../5health/${i}_bigip.conf ; done

global bigipbaseList 
bigipbaseList = []

global bigipList 
bigipList = []

global xlsxExport
xlsxExport=False

global targetXlsxFile
targetXlsxFile = ''

#########################
#File Operations
#########################

def checkBigipFile(bigipName):

    #Make sure the file can be opened
    try:
        bigipFile = open(bigipName, 'r')
    except OSError:
        print ('Could not open/read orignal config file:', bigipName)
        sys.exit()

    #Make sure the file is readable
    try:
        line = bigipFile.readline()
    except:
        print ('This file doesn\'t appear to be readable:', bigipName)
        sys.exit()
    else:
        if not "#TMSH-VERSION:" in line:
            print("This file doesn't appear to be a bigip configuration file.", bigipName)
            sys.exit()
    return bigipFile    

def buildBigipFileListFromPath(directory):

    global bigipbaseList, bigipList
    bigipbaseList=[]
    for filepath in pathlib.Path(directory).glob('**/*bigip_base.conf'):
        #print(filepath.absolute())
        bigipbaseList.append(filepath.absolute())

    bigipList=[]
    for filepath in pathlib.Path(directory).glob('**/*bigip.conf'):
        #print(filepath.absolute())
        bigipList.append(filepath.absolute())
   
def reorderBigipFileList():
    
    global bigipbaseList, bigipList
    baseCommonFileCounter=0
    commonFileCounter=0
    
    for f in bigipbaseList:
        baseCommonFile=checkBigipFile(f)
        for line in baseCommonFile:
            if "net route-domain /Common/0 {" in line:
                #print('found common bigipbase.conf',f)
                baseCommonFileCounter+=1
                ff=f
                break
        baseCommonFile.close()
        
    for g in bigipList:
        commonFile=checkBigipFile(g)
        for line in commonFile:
            if "ltm default-node-monitor {" in line:
                #print('found common bigip.conf',g)
                commonFileCounter+=1
                gg=g
                break
        commonFile.close()
        
    if baseCommonFileCounter>1 or baseCommonFileCounter==0:
        print('More or less than 1 bigip_base.conf found, aborting')
        sys.exit()
        
    if commonFileCounter>1  or commonFileCounter==0:
        print('More or less than 1 bigip.conf found, aborting')
        sys.exit()
        
    bigipbaseList.remove(ff)
    bigipbaseList.insert(0, ff)
    
    bigipList.remove(gg)
    bigipList.insert(0, gg)
      
#########################
#Execution parameters
#########################
        
class view(enum.IntEnum):
    literal = 0
    insights = 1
    reverse = 2
#    wide = 3

class mode(enum.IntEnum):
    brief = 1
    full = 2
    extended = 3
#    debug = 4        

#########################
#Comments            
#########################

class criticality(enum.IntEnum):
    #based on syslog
    error = 3
    warning = 4
    info = 6
    normal = 100

#########################
#Helpers            
#########################
            
def isolate(config):
    return re.sub('%[0-9]*', '', config.replace('{', '').replace('\n', '').replace(' ', '').lstrip().rstrip())
        
def determineIpType(address):
    try:
        if type(ipaddress.ip_address((re.split('/',str(address))[0]))) is ipaddress.IPv4Address:
            return(4)
        elif type(ipaddress.ip_address((re.split('/',str(address))[0])))  is ipaddress.IPv6Address:
            return(6)
    except:
        #print('not an ip address, probably an fqdn')
        return(0)    
        
def objectTypeToConfigurationArray(ltmObjectType, objectArray):
    n=ltmObjectType.__name__ 
    n += 's'
    if n=='rds':n='routeDomains' #FIX THIS
    return getattribute(objectArray, n )

def getattribute(obj, attribute):
    if attribute==None:
        return None
    if type(obj)==ltmObject:
        return None
    else:
        if "weakref" in str(obj):
            try:
                return getattr(obj(), attribute)

            except AttributeError:
                #print("There is no such attribute")
                return None
        else:
            try:
                return getattr(obj, attribute)

            except AttributeError:
                #print("There is no such attribute")
                return None
   
def flag(priority):
    if (priority==criticality.error):
        f = "\033[1m\033[91m[Error]\033[0m\033[0m"
    if (priority==criticality.warning):
        f ="\033[1m\033[93m[Warning]\033[0m\033[0m"
    if (priority==criticality.info):
        f = "\033[1m\033[92m[Info]\033[0m\033[0m"
    return f

def unformat(description):
    return description.replace("%s ","").replace(": %s","")

def chunks(objectArray, chunkSize):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(objectArray), chunkSize):
        yield objectArray[i:i + chunkSize]

def colorize(string,p=criticality.normal):

    tmp = string.split('\n')
    tmp2 = ''
    
    for t in tmp:
        if(p==criticality.error):
            tmp2+=('\033[91m'+str(t)+'\033[0m')+'\n'                 
        elif(p==criticality.warning):
            tmp2+=('\033[93m'+str(t)+'\033[0m')+'\n'
        elif(p==criticality.info):
            tmp2+=('\033[92m'+str(t)+'\033[0m')+'\n'
        elif(p==94): #tofix
            tmp2+=('\033[94m'+str(t)+'\033[0m')+'\n'
        elif(p==33): #tofix
            tmp2+=('\033[35m'+str(t)+'\033[0m')+'\n'
        else:
            tmp2+=('\033[2m'+str(t)+'\033[0m')+'\n'
            
    return tmp2.rstrip('\n')

def underlinize(string):
        return(('\033[4m'+str(string)+'\033[0m').strip())

def bolderize(string):
        return(('\033[1m'+str(string)+'\033[0m').strip())

def extractRD(address):

    if '%' in address:
        r = re.search('%[0-9]*', address)
        r=r.group(0)
        return r.replace('%','')
    else:
        return '0'
    
def pause():
      #input("\nPress Enter to continue...\n")
      pass
  
def noInfo():
    print('\n no information to display in this view \n') 
    
#########################
#Config operations
#########################

def removeConfigSegment(configSegment, pattern):

    queue = deque([])
    patternMatched=False
    patternStart = re.compile(pattern)
    patternOpenBracket = re.compile('.*{.*')
    patternCloseBracket = re.compile('.*}.*')

    for line in configSegment.split('\n'):
       queue.append(line+'\n')
       if patternStart.search(line):
           patternMatched=True
       if patternCloseBracket.search(line):
           if(patternMatched==True):
                while patternOpenBracket.search(queue[-1])==None:
                    queue.pop()
                if(patternStart.search(queue[-1])!=None):
                    patternMatched=False
                queue.pop()
    
    resultConfigSegment=''.join(queue)

    return resultConfigSegment

def extractConfigSegment(configSegment, pattern):

    patternMatched=False
    patternStart = re.compile(pattern)
    patternOpenBracket = re.compile('.*{.*')
    patternCloseBracket = re.compile('.*}.*')
    patternNestedInline = re.compile('[\s]*.*{.*}.*')

    counterNest=0
    resultConfigSegment =''

    for line in configSegment.split('\n'):
       if patternStart.search(line):
           patternMatched=True
           counterNest+=1
           resultConfigSegment+=line+'\n'
       elif patternNestedInline.search(line):
           if(patternMatched and counterNest>0):
                resultConfigSegment+=line+'\n'
       elif patternCloseBracket.search(line):
           if(patternMatched and counterNest>0):
                resultConfigSegment+=line+'\n'
                counterNest-=1
                if(counterNest==0):
                    patternMatched=False
       elif patternOpenBracket.search(line):
           if(patternMatched and counterNest>0):
                resultConfigSegment+=line+'\n'
                counterNest+=1
       else:
           if(patternMatched and counterNest>0):
                resultConfigSegment+=line+'\n'

    return resultConfigSegment
 
######################
# Reporting
######################

class comment:

    def __init__(self='none', description=None, priority=None): #Check None here
        self.description: str = description
        self.priority: int =  priority
        self.objects = []
        
    def populate():
        
        print("\n\r") 
        print('[*] Initializing Comments Table - ', end='')
        result.comments[0] = (comment('Dummy',0))
        
        result.comments[10] = (comment('VLAN %s has no IPv4 network attached.',criticality.error)) #Orphan
        result.comments[11] = (comment('VLAN %s has more than one IPv4 network attached.',criticality.error)) #Orphan
        result.comments[12] = (comment('VLAN %s has no IPv6 network attached.',criticality.error)) #Orphan
        result.comments[13] = (comment('VLAN %s has more than one IPv6 network attached.',criticality.error)) #Orphan
        result.comments[14] = (comment('VLAN %s is used for a route next-hop.',criticality.info))
        
        result.comments[101] = (comment('VLAN %s has no IPv4 Self-IP.',criticality.error)) #Orphan
        result.comments[102] = (comment('VLAN %s has no Static IPv4 Self-IP.',criticality.error))
        result.comments[103] = (comment('VLAN %s has no Floating IPv4 Self-IP.',criticality.error))
        result.comments[104] = (comment('VLAN %s has multiple Static IPv4 Self-IP.',criticality.error))
        result.comments[105] = (comment('VLAN %s has multiple Floating IPv4 Self-IP.',criticality.error))
        result.comments[106] = (comment('VLAN %s is Client-Side only (Only VS) for IPv4.',criticality.info))
        result.comments[107] = (comment('VLAN %s is Server-Side only (Only Nodes) for IPv4.',criticality.info))
        result.comments[108] = (comment('VLAN %s is shared Client/Server-Side (VS and Nodes) for IPv4.',criticality.info))
        result.comments[109] = (comment('VLAN %s has no LTM objects (No VS and no Nodes) for IPv4.',criticality.warning))#Orphan
        result.comments[110] = (comment('VLAN %s has IPv4 self-IP addresses on multiple subnets.',criticality.warning))#Orphan

        result.comments[121] = (comment('VLAN %s has no IPv6 Self-IP.',criticality.error)) #Orphan
        result.comments[122] = (comment('VLAN %s has no Static IPv6 Self-IP.',criticality.error))
        result.comments[123] = (comment('VLAN %s has no Floating IPv6 Self-IP.',criticality.error))
        result.comments[124] = (comment('VLAN %s has multiple Static IPv6 Self-IP.',criticality.error))
        result.comments[125] = (comment('VLAN %s has multiple Floating IPv6 Self-IP.',criticality.error))
        result.comments[126] = (comment('VLAN %s is Client-Side only (Only VS) for IPv6.',criticality.info))
        result.comments[127] = (comment('VLAN %s is Server-Side only (Only Nodes) for IPv6.',criticality.info))
        result.comments[128] = (comment('VLAN %s is shared Client/Server-Side (VS and Nodes) for IPv6.',criticality.info))
        result.comments[129] = (comment('VLAN %s has no LTM objects (No VS and no Nodes) for IPv6.',criticality.warning))#Orphan
        result.comments[130] = (comment('VLAN %s has IPv6 self-IP addresses on multiple subnets.',criticality.warning))#Orphan

        result.comments[201] = (comment('Static IPv4 Self-IP %s belongs to a VLAN that has no Floating IPv4 Self-IP.',criticality.error))
        result.comments[202] = (comment('Static IPv4 Self-IP %s belongs to a VLAN that has too many Floating IPv4 Self-IP.',criticality.error))
        result.comments[203] = (comment('Static IPv4 Self-IP %s belongs to a VLAN that has too many Static IPv4 Self-IP.',criticality.error))
        result.comments[204] = (comment('Floating IPv4 Self-IP %s belongs to a VLAN that has no Static IPv4 Self-IP.',criticality.error))
        result.comments[205] = (comment('Floating IPv4 Self-IP %s belongs to a VLAN that has too many Static IPv4 Self-IP.',criticality.error))
        result.comments[206] = (comment('Floating IPv4 Self-IP %s belongs to a VLAN that has too many Floating IPv4 Self-IP.',criticality.error))
        result.comments[207] = (comment('IPv4 Self-IP %s belongs to a VLAN that has Self-IP addresses on other IPv4 subnets.',criticality.error))
        
        result.comments[221] = (comment('Static IPv6 Self-IP %s belongs to a VLAN that has no Floating IPv6 Self-IP.',criticality.error))
        result.comments[222] = (comment('Static IPv6 Self-IP %s belongs to a VLAN that has too many Floating IPv6 Self-IP.',criticality.error))
        result.comments[223] = (comment('Static IPv6 Self-IP %s belongs to a VLAN that has too many Static IPv6 Self-IP.',criticality.error))
        result.comments[224] = (comment('Floating IPv6 Self-IP %s belongs to a VLAN that has no Static IPv6 Self-IP.',criticality.error))
        result.comments[225] = (comment('Floating IPv6 Self-IP %s belongs to a VLAN that has too many Static IPv6 Self-IP.',criticality.error))
        result.comments[226] = (comment('Floating IPv6 Self-IP %s belongs to a VLAN that has too many Floating IPv6 Self-IP.',criticality.error))
        result.comments[227] = (comment('IPv6 Self-IP %s belongs to a VLAN that has Self-IP addresses on other IPv6 subnets.',criticality.error))
        
        result.comments[301] = (comment('Route %s is unnecessary, network is already directly connected via VLAN.',criticality.warning))
        result.comments[302] = (comment('Route %s is unnecessary, no objects are accessible via this route.',criticality.warning)) #Not Done
        result.comments[303] = (comment('There are no default IPv4 route configured.',criticality.warning))
        result.comments[304] = (comment('There are no default IPv6 route configured.',criticality.warning))

        result.comments[401] = (comment('LTM Node %s is not used in any of the LTM pool.',criticality.warning))
        result.comments[402] = (comment('LTM Node %s is not reachable via any of the configured routes or vlans.',criticality.error))
        result.comments[403] = (comment('LTM Node %s is only reachable via the default route.',criticality.info))

        result.comments[501] = (comment('LTM Pool %s is empty.',criticality.warning))        
        result.comments[502] = (comment('LTM Pool %s has LTM nodes on different vlan.',criticality.warning))
        result.comments[503] = (comment('LTM Pool %s has a mix of directly connected and routed LTM nodes.',criticality.warning))
        result.comments[504] = (comment('LTM Pool %s is not attached to any LTM virtual server (could be used within irules, use 5bulator.py to find out which pools are used from which irules).',criticality.warning))

        result.comments[601] = (comment('LTM Virtual server %s is on the same vlan as all of its LTM pool members (one-arm).',criticality.info))
        result.comments[602] = (comment('LTM Virtual server %s is on the same vlan as some of its LTM pool members.',criticality.warning))
        result.comments[603] = (comment('LTM Virtual server %s is on a different vlan than all its LTM pool members (inline).',criticality.info))
        result.comments[604] = (comment('LTM Virtual server %s has no LTM pool attached.',criticality.warning))
                
        print(len(result.comments))
        print("\r") 
        
######################
# Data Structures NW
######################

class ltmObject:
    def __init__(self, name='none', comments=None, orphan=False ):
        self.name: str = name
        self.comments = []    
        self.orphan = False

class globalSettings(ltmObject):
    
    def __init__(self, name='none'):
        
        ltmObject.__init__(self, name, None)
        self.hostname = None
        
    def process(config):
        global bigipconfiguration
        gs= globalSettings()
        
        #What does this do again ?
        settings =isolate(re.search('(^sys global-settings(.*))',config).group(0).replace('sys global-settings', ''))
        if settings:
            gs.name=settings.strip()
        
        hostname = re.search('([\s]+hostname .*)',config)
        if hostname:
            hostname =isolate(hostname.group(0).replace('hostname', ''))
            gs.hostname=hostname.strip()
            bigipconfiguration.hostname=gs.hostname
    
class deviceGroup(ltmObject):
    
    def __init__(self, name='none'):
        
        ltmObject.__init__(self, name, None)
        self.devices = []
        self.type = None
        self.clusterSize=0
        
    def process(config):
        global bigipconfiguration
        dg= deviceGroup()
        
        name =isolate(re.search('(^cm device-group (.*))',config).group(0).replace('cm device-group', ''))
        if name:
            dg.name=name.strip()
        
        type = re.search('([\s]+type .*)',config)
        if type:
            type =isolate(type.group(0).replace('type', ''))
            dg.type=type.strip()
            if dg.type=='sync-failover':
            
                devicesList = extractConfigSegment(config,'([\s]*devices\s{)')
                devicesList = re.sub('[\s]*devices\s{','',devicesList, flags=re.M)
                devicesList = re.sub('(^[\s]*})','',devicesList, flags=re.M)
                devicesList = re.sub('(^[\s]*)','',devicesList, flags=re.M)
                devicesList = devicesList.strip()

                nlines = len(devicesList.splitlines())
                if nlines>=2:
                    bigipconfiguration.isHA=True
    
class rd(ltmObject):
    def __init__(self, name='none', id=0):
        ltmObject.__init__(self, name, None)
        self.vlanConfList = []
        self.id: str = id
        self.vlans = []
        
    def process(config):
        global bigipconfiguration
        r = rd()
        
        if not config==None:
        
            name =isolate(re.search('(^net route-domain (.*))',config).group(0).replace('net route-domain', ''))
            if name:
                r.name=name.strip()
            
            id =isolate(re.search('([\s]+id .*)',config).group(0).replace('id', ''))
            if id:
                r.id=id.strip()
            
            vlans =extractConfigSegment(config,'([\s]*vlans\s{)')
            vlans = re.sub('(^[\s]*vlans([\n]|[\s].*))','',vlans, flags=re.M)
            vlans = re.sub('(^[\s]*})','',vlans, flags=re.M)
            vlans = re.sub('(^[\s]+)','',vlans, flags=re.M)

            if vlans:
                vlans=vlans.strip().split()
                r.vlanConfList=vlans
                for v1 in vlans:
                    for v2 in bigipconfiguration.vlans:
                        if v1 == v2.name:
                            r.vlans.append(v2)
                            v2.rd=r
                                    
            bigipconfiguration.routeDomains.append(r)
    
    def isVlanInRDVlanList(self,name):
        for vname in self.vlanConfList:
            if str(vname)==str(name):
                return True
        return False
    
    def audit():
        
        nRD=len(bigipconfiguration.routeDomains)
        if nRD>1:
            bigipconfiguration.hasRouteDomains=True
        elif nRD==1:
            if bigipconfiguration.routeDomains[0].id=='0':
                bigipconfiguration.hasRouteDomains=False
            else:
                bigipconfiguration.hasRouteDomains=True
            
    def getVlanByName(self, name):
        for v in self.vlans:
            if v.name==name:
                return v        
        return None

    def getVlanByAddress(self, address):
        t=determineIpType(address)
        
        if t==4:
            for v in self.vlans:
                for n in v.network4:
                    if ipaddress.IPv4Network(address).subnet_of(n.prefix):
                        return v
            return None
                    
        if t==6:
            for v in self.vlans:
                for n in v.network6:
                    if ipaddress.IPv6Network(address).subnet_of(n.prefix):
                        return v
            return None

class network(ltmObject):
    
    def __init__(self, name='none', counterNull = 0, comments=None):
        ltmObject.__init__(self, name, comments)
        
        self.prefix = None
        self.version = 4
        self.selfips = []
        self.virtuals = []
        self.nodes = []
        self.vlan = None
        
        self.counterSelfStatic = counterNull
        self.counterSelfFloating = counterNull
        self.counterVirtuals = counterNull
        self.counterNodes = counterNull
         
    def audit4(self):
        
        self.counterVirtuals=len(self.virtuals)
        self.counterNodes=len(self.nodes)
        self.counterSelfStatic=0
        self.counterSelfFloating=0
        
        ############################################
        # Conflict with audit at the self level
        ############################################
        
        for s in self.selfips: 
            if s.kind=="static":
                self.counterSelfStatic+=1
            if s.kind=="floating":
                self.counterSelfFloating+=1
                
        #No Self-IP
        if self.counterSelfFloating+self.counterSelfStatic==0:
            if len( getattr(self.vlan,'network4'))==1:
                bigipconfiguration.attachObjectToComment(self.vlan, 101, True)
            else:
                bigipconfiguration.attachObjectToComment(self, 101, True)
                
        else:
            #No Static 
            if self.counterSelfStatic==0:
                if len( getattr(self.vlan,'network4'))==1:
                    bigipconfiguration.attachObjectToComment(self.vlan, 102)
                else:
                    bigipconfiguration.attachObjectToComment(self, 102)
                    
            #No Floating and no float detected at all (i.e standalone unit)        
            elif (bigipconfiguration.isHA and self.counterSelfFloating==0):
                if len( getattr(self.vlan,'network4'))==1:
                    bigipconfiguration.attachObjectToComment(self.vlan, 103)
                else:
                    bigipconfiguration.attachObjectToComment(self, 103)
                    
        #Too many static:            
        if self.counterSelfStatic>1:
            if len( getattr(self.vlan,'network4'))==1:
                bigipconfiguration.attachObjectToComment(self.vlan, 104)
            else:
                bigipconfiguration.attachObjectToComment(self, 104)
                
        #Too many float:
        if self.counterSelfFloating>1:
            if len( getattr(self.vlan,'network4'))==1:
                bigipconfiguration.attachObjectToComment(self.vlan, 105)
            else:
                bigipconfiguration.attachObjectToComment(self, 105)
            
        #No LTM Objects on the VLAN:
        if self.counterNodes==0 and self.counterVirtuals==0:
            if len( getattr(self.vlan,'network4'))==1:
                bigipconfiguration.attachObjectToComment(self.vlan, 109)
            else:
                bigipconfiguration.attachObjectToComment(self, 109)
        else:
            #No LTM nodes on the VLAN:
            if self.counterNodes==0:
                if len( getattr(self.vlan,'network4'))==1:
                    bigipconfiguration.attachObjectToComment(self.vlan, 106)
                else:
                    bigipconfiguration.attachObjectToComment(self, 106)
                
            #No LTM nodes on the VLAN:
            if self.counterVirtuals==0:
                if len( getattr(self.vlan,'network4'))==1:
                    bigipconfiguration.attachObjectToComment(self.vlan, 107)
                else:
                    bigipconfiguration.attachObjectToComment(self, 107)
            
        #Both Virtual and nodes on the VLAN:
        if not self.counterNodes==0 and not self.counterVirtuals==0:
            if len( getattr(self.vlan,'network4'))==1:
                bigipconfiguration.attachObjectToComment(self.vlan, 108)
            else:
                bigipconfiguration.attachObjectToComment(self, 108)

    def audit6(self):
        
        self.counterVirtuals=len(self.virtuals)
        self.counterNodes=len(self.nodes)
        self.counterSelfStatic=0
        self.counterSelfFloating=0
        
        ############################################
        # Conflict with audit at the self level
        ############################################
        
        for s in self.selfips: 
            if s.kind=="static":
                self.counterSelfStatic+=1
            if s.kind=="floating":
                self.counterSelfFloating+=1
                
        #No Self-IP
        if self.counterSelfFloating+self.counterSelfStatic==0:
            if len( getattr(self.vlan,'network6'))==1:
                bigipconfiguration.attachObjectToComment(self.vlan, 121, True)
            else:
                bigipconfiguration.attachObjectToComment(self, 121, True)
                
        else:
            #No Static 
            if self.counterSelfStatic==0:
                if len( getattr(self.vlan,'network6'))==1:
                    bigipconfiguration.attachObjectToComment(self.vlan, 122)
                else:
                    bigipconfiguration.attachObjectToComment(self, 122)
                    
            #No Floating and no float detected at all (i.e standalone unit)        
            elif (bigipconfiguration.isHA and self.counterSelfFloating==0):
                if len( getattr(self.vlan,'network6'))==1:
                    bigipconfiguration.attachObjectToComment(self.vlan, 123)
                else:
                    bigipconfiguration.attachObjectToComment(self, 123)
                    
        #Too many static:            
        if self.counterSelfStatic>1:
            if len( getattr(self.vlan,'network6'))==1:
                bigipconfiguration.attachObjectToComment(self.vlan, 124)
            else:
                bigipconfiguration.attachObjectToComment(self, 124)
                
        #Too many float:
        if self.counterSelfFloating>1:
            if len( getattr(self.vlan,'network6'))==1:
                bigipconfiguration.attachObjectToComment(self.vlan, 125)
            else:
                bigipconfiguration.attachObjectToComment(self, 125)
            
        #No LTM Objects on the VLAN:
        if self.counterNodes==0 and self.counterVirtuals==0:
            if len( getattr(self.vlan,'network6'))==1:
                bigipconfiguration.attachObjectToComment(self.vlan, 129)
            else:
                bigipconfiguration.attachObjectToComment(self, 129)
        else:
            #No LTM nodes on the VLAN:
            if self.counterNodes==0:
                if len( getattr(self.vlan,'network6'))==1:
                    bigipconfiguration.attachObjectToComment(self.vlan, 126)
                else:
                    bigipconfiguration.attachObjectToComment(self, 126)
                
            #No LTM nodes on the VLAN:
            if self.counterVirtuals==0:
                if len( getattr(self.vlan,'network6'))==1:
                    bigipconfiguration.attachObjectToComment(self.vlan, 127)
                else:
                    bigipconfiguration.attachObjectToComment(self, 127)
            
        #Both Virtual and nodes on the VLAN:
        if not self.counterNodes==0 and not self.counterVirtuals==0:
            if len( getattr(self.vlan,'network6'))==1:
                bigipconfiguration.attachObjectToComment(self.vlan, 128)
            else:
                bigipconfiguration.attachObjectToComment(self, 128)

    def getNumberOfSelf(self, kind):
        counter=0
        for s in self.selfips:
            if s.kind==kind:
                counter+=1
        return int(counter)   

class vlan(ltmObject):
  
    def __init__(self, name='none', tag='none', counterNull = 0, comments=None ):
        ltmObject.__init__(self, name, comments)
        self.tag: str = tag
        
        self.network4 = []
        self.network6 = []
        
        self.rd = None
        self.routes = []
        
        self.counterVirtuals4=0
        self.counterNodes4=0
        self.counterSelfStatic4=0
        self.counterSelfFloating4=0
        
        self.counterVirtuals6=0
        self.counterNodes6=0
        self.counterSelfStatic6=0
        self.counterSelfFloating6=0
        
        self.counterVirtualsTotal=0
        self.counterNodesTotal=0
        self.counterSelfStaticTotal=0
        self.counterSelfFloatingTotal=0
        
    def process(config):
        global bigipconfiguration
        v = vlan()

        name =isolate(re.search('(^net vlan (.*))',config).group(0).replace('net vlan', ''))
        if name:
            v.name=name.strip()
        #else return

        tag =isolate(re.search('([\s]+tag .*)',config).group(0).replace('\n', '').replace('tag', ''))
        if tag==None:
            tag = 0
        v.tag=tag

        #####################################
        # Attach VLAN to their Configuration
        #####################################

        if bigipconfiguration.getVlanByName(v.name)==None:
            bigipconfiguration.vlans.append(v)
 
    def audit():
        
        print('[*] Auditing configuration - Vlans.')
        
        if bigipconfiguration.isIPv4:
            for v in bigipconfiguration.vlans:
                
                if len(v.network4)==0:
                    bigipconfiguration.attachObjectToComment(v, 10)
                    
                elif len(v.network4)>1:
                    bigipconfiguration.attachObjectToComment(v, 11)
            
                for n4 in v.network4:
                    n4.audit4()
                    pass
            
        if bigipconfiguration.isIPv6:
            for v in bigipconfiguration.vlans:            
            
                if len(v.network6)==0:
                    bigipconfiguration.attachObjectToComment(v, 12)
                    
                elif len(v.network6)>1:
                    bigipconfiguration.attachObjectToComment(v, 13)    

                for n6 in v.network6:
                    n6.audit6()
                    pass           
             
    def getVlanNetworkFromAddress(self, address, version):
            
        if version ==4:
        
            for w in  self.network4:
                if ipaddress.IPv4Network(address,False).subnet_of(w.prefix):
                    return w
            return None
                
        elif version ==6:
        
            for w in  self.network6:
                if ipaddress.IPv6Network(address,False).subnet_of(w.prefix):
                    return w
            return None
                
        else:
            return None

    def postProcess(self):
        
        for n in self.network4:
            self.counterVirtuals4+=n.counterVirtuals
            self.counterNodes4+=n.counterNodes
            self.counterSelfStatic4=n.counterSelfStatic
            self.counterSelfFloating4=n.counterSelfFloating
            
        for n in self.network6:
            self.counterVirtuals6+=n.counterVirtuals
            self.counterNodes6+=n.counterNodes
            self.counterSelfStatic6=n.counterSelfStatic
            self.counterSelfFloating6=n.counterSelfFloating
        
        self.counterVirtualsTotal      = self.counterVirtuals4+self.counterVirtuals6
        self.counterNodesTotal         = self.counterNodes4+self.counterNodes6
        self.counterSelfStaticTotal    = self.counterSelfStatic4+self.counterSelfStatic6
        self.counterSelfFloatingTotal  = self.counterSelfFloating4+self.counterSelfFloating6

        
        # if self.counterSelfStatic4+self.counterSelfFloating4+self.counterSelfStatic6+self.counterSelfFloating6==0:
        #     bigipconfiguration.attachOrphanObjectToConfiguration(self)
        #     pass#orphan
        
        # elif self.counterVirtuals4+self.counterNodes4+self.counterVirtuals6+self.counterNodes6==0:
        #     bigipconfiguration.attachOrphanObjectToConfiguration(self)
        #     pass#orphan

        if len(self.routes)==0:
            if self.counterSelfStatic4+self.counterSelfFloating4+self.counterSelfStatic6+self.counterSelfFloating6==0:
                bigipconfiguration.attachOrphanObjectToConfiguration(self)
                pass#orphan
            
            elif self.counterVirtuals4+self.counterNodes4+self.counterVirtuals6+self.counterNodes6==0:
                bigipconfiguration.attachOrphanObjectToConfiguration(self)
                pass#orphan
        else:
            bigipconfiguration.attachObjectToComment(self, 14)

class selfip(ltmObject):

    def __init__(self, name='none', kind='none', address='none', comments=None):
        
        ltmObject.__init__(self, name, comments)
        self.kind: str = kind
        self.address: str = address
        self.vlan = None

    def process(config):
        global bigipconfiguration
        s = selfip()
        v = None
        r=''

        #####################################
        # Extract info from self from config
        #####################################

        config = re.sub('(^[\s]*inherited-traffic-group([\n]|[\s].*))','',config, flags=re.M)

        name =re.search('(^net self (.*))',config)
        if name:
            s.name=isolate(name.group(0).replace('net self', ''))

        address =re.search('([\s]*address (.*))',config)
        if address:
            r=extractRD(address.group(0))
            s.address=isolate(address.group(0).replace('address', ''))
            
        kind =re.search('([\s]*traffic-group (.*))',config)
        if kind:
            kind=isolate(kind.group(0).replace('traffic-group ', '')).split('/')[2]
            if kind=='traffic-group-local-only': #ambiguity on possible other traffic groups, to be reviewed
                    s.kind='static'
            else:
                    s.kind='floating'

        vl =re.search('([\s]+vlan (.*))',config) # dont seem to be able to use ^ in the regex.
        if vl:
            vl=isolate(vl.group(0).replace('vlan ', ''))
            
        ##########################################
        # Attach Self to config and to their VLANs
        ##########################################                
    
        rd1=bigipconfiguration.getRdByID(r)
        
        if not rd1==None:
            v=rd1.getVlanByName(vl)

        if not v == None:
            
            if determineIpType(s.address)==4:
                
                if (len(v.network4)==0):   #No network stored yet  
                    
                    w=network()
                    w.prefix=ipaddress.ip_network(s.address, strict=False)
                    w.version=4
                    #w.selfips.append(s)
                    w.vlan=v
                    w.name=str(v.name)+'('+str(w.prefix)+')'
                    v.network4.append(w)
                    bigipconfiguration.isIPv4=True
                
                else: #Network list is not empty
                    n = v.getVlanNetworkFromAddress( ipaddress.ip_network(s.address, strict=False), 4)
                    
                    #network exists already:
                    if not n==None:
                        #n.selfips.append(s)
                        pass
                    #network doesnt exist yet:    
                    else:
                        w=network()
                        w.prefix=ipaddress.ip_network(s.address, strict=False)
                        w.version=4
                        #w.selfips.append(s)
                        w.vlan=v
                        w.name=str(v.name)+'('+str(w.prefix)+')'
                        v.network4.append(w)
                        
                s.vlan=v #remove?
                bigipconfiguration.attachObjectToConfiguration(s,(v,))
                return

            elif determineIpType(s.address)==6:

                if (len(v.network6)==0):   #No network stored yet  
                    
                    w=network()
                    w.prefix=ipaddress.ip_network(s.address, strict=False)
                    w.version=6
                    w.selfips.append(s)
                    w.vlan=v
                    v.network6.append(w)
                    bigipconfiguration.isIPv6=True
                    
                else: #Network list is not empty
                    n = v.getVlanNetworkFromAddress( ipaddress.ip_network(s.address, strict=False),6)
                    
                    #network exist already:
                    if not n==None:
                        n.selfips.append(s)
                    #network doesnt exist yet:    
                    else:
                        w=network()
                        w.prefix=ipaddress.ip_network(s.address, strict=False)
                        w.version=6
                        w.selfips.append(s)
                        w.vlan=v 
                        v.network6.append(w)
                        
                    s.vlan=v
                    bigipconfiguration.attachObjectToConfiguration(s,(v,))
                    return

            else:
                print('Error - invalid ip address type')
                s.vlan=v
                bigipconfiguration.attachObjectToConfiguration(s)
                return

        else:
            #add case where there could be a tunnel instead of a vlan
            print('Error - no vlan found on this route domain for this selfip : ', s.name)
            bigipconfiguration.attachObjectToConfiguration(s)
            return
   
    def audit():
        print('[*] Auditing configuration - Selfips.')
        
        #check if there are too many self on the VLAN where this self belongs
        for s in bigipconfiguration.selfips:
            
            if (s.vlan!=None):  

                n = s.vlan.getVlanNetworkFromAddress( ipaddress.ip_network(s.address, strict=False),  determineIpType(ipaddress.ip_network(s.address, strict=False)))
                
                staticCounter = n.getNumberOfSelf('static')
                floatCounter = n.getNumberOfSelf('floating')
                    
                if (s.kind=='static'):  
                    
                    if ( int(floatCounter) == 0 ) :
                        if determineIpType(s.address)==4:
                            bigipconfiguration.attachObjectToComment(s, 201)
                        elif determineIpType(s.address)==6:
                            bigipconfiguration.attachObjectToComment(s, 221)                            
                    elif ( int(floatCounter) > 1 ) :
                        if determineIpType(s.address)==4:
                            bigipconfiguration.attachObjectToComment(s, 202)
                        elif determineIpType(s.address)==6:
                            bigipconfiguration.attachObjectToComment(s, 222)                                              
                    elif ( int(staticCounter) > 1 ) :
                        if determineIpType(s.address)==4:
                            bigipconfiguration.attachObjectToComment(s, 203)
                        elif determineIpType(s.address)==6:
                            bigipconfiguration.attachObjectToComment(s, 223)                               

                if (s.kind=='floating'):                        

                    if ( int(floatCounter) == 0 ) :
                        if determineIpType(s.address)==4:
                            bigipconfiguration.attachObjectToComment(s, 204)
                        elif determineIpType(s.address)==6:
                            bigipconfiguration.attachObjectToComment(s, 224)                            
                    elif ( int(floatCounter) > 1 ) :
                        if determineIpType(s.address)==4:
                            bigipconfiguration.attachObjectToComment(s, 205)
                        elif determineIpType(s.address)==6:
                            bigipconfiguration.attachObjectToComment(s, 225)                                              
                    elif ( int(staticCounter) > 1 ) :
                        if determineIpType(s.address)==4:
                            bigipconfiguration.attachObjectToComment(s, 206)
                        elif determineIpType(s.address)==6:
                            bigipconfiguration.attachObjectToComment(s, 226)       
                                    
        for s in bigipconfiguration.selfips:

            if (s.vlan!=None):
                if determineIpType(s.address)==4:
                    if len(s.vlan.network4)>1:
                        bigipconfiguration.attachObjectToComment(s.vlan, 110)
                        bigipconfiguration.attachObjectToComment(s, 207)
                    if len(s.vlan.network6)>1:
                        bigipconfiguration.attachObjectToComment(s.vlan, 130)
                        bigipconfiguration.attachObjectToComment(s, 227)
            
    def postProcess(self):
        #Not attached to an existing vlan
        if self.vlan==None:
            bigipconfiguration.attachOrphanObjectToConfiguration(self)
               
class gw(ltmObject):

    def __init__(self, name='none', address='none', comments=None):
        
        ltmObject.__init__(self, name, comments)
        self.address: str = address
        self.vlan = None
        self.route = None

class destination(ltmObject):

    def __init__(self, name='none', network='none', comments=None):
        
        ltmObject.__init__(self, name, comments)
        self.network: str = network
        self.rd = None

class route(ltmObject):
    
    def __init__(self, name='none', counterNodes=0, comments=None):
        
        ltmObject.__init__(self, name, comments)
        self.destination: str = destination
        self.gw = gw
        self.interface = None
        self.pool = None
        self.egressvlan = []
        self.overlap_vlan = None
        self.nodes = []
        
        self.counterNodes = counterNodes

    def process(config):
        global bigipconfiguration
        r = route()
        d = destination()
        g = gw()
        p = pool()
        r2 = ''
     
        #####################################
        # Extract info from route from config
        #####################################

        name = re.search('(^net route (.*))',config)
        if name:
            r.name=isolate(name.group(0).replace('net route', ''))

        network = re.search('([\s]network (.*))',config)
        if network:
            r2 = bigipconfiguration.getRdByID(extractRD(network.group(0)))
            if  ((str(network)).find("default-inet6") == -1): #modify that
                network=isolate(network.group(0).replace('network', '')).replace('default','0.0.0.0/0')
            else:
                network="::/0" 
            d.rd = r2        
            d.network=network
            if d.network=='0.0.0.0/0':
                bigipconfiguration.hasDefaultRoute4=True
            elif d.network=='::/0':
                bigipconfiguration.hasDefaultRoute6=True
                
            r.destination=d

        gateway = re.search('([\s]gw (.*))',config)
        if gateway:
            r2= bigipconfiguration.getRdByID(extractRD(gateway.group(0)))
            g.address=isolate(gateway.group(0).replace('gw', ''))
            g.vlan=r2.getVlanByAddress(g.address)            
            r.gw=g
            r.egressvlan.append(g.vlan)
                  
        interface = re.search('([\s]interface (.*))',config)
        if interface:
            r.interface=bigipconfiguration.getVlanByName(isolate(interface.group(0).replace('interface', '')))
            r.egressvlan.append(r.interface)

        poolname = re.search('([\s]pool (.*))',config)
        if poolname:
            p.name=isolate(poolname.group(0).replace('pool', ''))
            r.pool=p#We ll replace this dummy pool by the actual ltm pool once reach ltm pool scanning 
            
        #####################################
        # Attach route to its VLAN
        #####################################

        bigipconfiguration.routes.append(r)#use attachObjectToConfiguration

    def audit():
        print('[*] Auditing configuration - Routes.')
 
        #checking overlap between routes and vlans
        for r in bigipconfiguration.routes:
            
            if determineIpType(r.destination.network)==4:
                t= 'network4'
                address2network=ipaddress.IPv4Network
                defaultSubnet='0.0.0.0/0'
            elif determineIpType(r.destination.network)==6:
                t= 'network6'
                address2network=ipaddress.IPv6Network
                defaultSubnet='::/0'
            else:
                print('error - unknown IP version on this route')

            if (r.destination.network!=defaultSubnet):                
                for v in bigipconfiguration.vlans:
                    
                    if getattr(v, t)!='none': #None
                        o=getattr(v, t)
                        for p in o:
                            q=address2network(p.prefix)
                            if address2network(r.destination.network).subnet_of(q):
                                r.overlap_vlan=weakref.ref(v)
                                bigipconfiguration.attachObjectToComment(r, 301, True) 
            
            #Reference route from its GW vlan.
            #bigipconfiguration.routes[0].gw.vlan.routes.append(weakref.ref(r))
            r.gw.vlan.routes.append(r)
            
            #checking if route point to no nodes.
            if (len(r.nodes)==0):
                bigipconfiguration.attachObjectToComment(r, 302)
                
        #checking If a default route is configured:
        if(bigipconfiguration.hasDefaultRoute4 == False):
            bigipconfiguration.attachObjectToComment(bigipconfiguration, 303)
            
        if(bigipconfiguration.hasDefaultRoute6 == False):
            bigipconfiguration.attachObjectToComment(bigipconfiguration, 304)

    def postProcess(self):
        self.counterNodes = len(self.nodes)
        #print('number of nodes attached to route: %i' % self.counterNodes  )
        if self.counterNodes==0:
            bigipconfiguration.attachOrphanObjectToConfiguration(self)

######################
# Data Structures LTM
######################

class node(ltmObject):
    
    def __init__(self, name='none', address='none', counterPools = 0, counterVirtuals = 0, comments=None):    
        ltmObject.__init__(self, name, comments)
        self.address: str = address
        self.vlan = None 
        self.route = None
        self.pools = []
        self.virtuals = []
        self.rd = None
        
        self.counterPools = counterPools
        self.counterVirtuals = counterVirtuals

    def process(config):
        global bigipconfiguration

        n = node()
        fqdn = False
        
        #####################################
        # Extract info from node from config
        #####################################

        name =re.search('(^ltm node (.*))',config)
        if name:
            n.name=name.group(0).replace('ltm node', '').replace('{','').lstrip().rstrip()

        address =re.search('([\s]address (.*))',config)
        if address:
            n.address=isolate(address.group(0).replace('address', ''))
        else:
            fqdn=True
            n.address= '225.5.5.5'#fqdn node, cannot be assessed, putting  a multicast address for now  FIX THIS

        r=str(extractRD(str(address)))
        
        if not fqdn:
            n.rd=bigipconfiguration.getRdByID(r)
        else:
            n.rd=bigipconfiguration.getRdByID('0')

        #####################################
        # Attach node to its VLAN or Route
        #####################################
        
        if not fqdn:
            
            v=n.rd.getVlanByAddress(n.address)
            if not v==None:
                n.vlan=v
                n.route=None
                
                if determineIpType(n.address)==4:
                    w=v.getVlanNetworkFromAddress(n.address,4)
                elif determineIpType(n.address)==6:
                    w=v.getVlanNetworkFromAddress(n.address,6)

                if not type(w)!=None:
                    w.nodes.append(n)
                
                bigipconfiguration.attachObjectToConfiguration(n,(v,))
                return
            
            r=bigipconfiguration.getRouteByRdAndAddress(n.rd, n.address)
            if not r==None:
                n.vlan=None
                n.route=r
                bigipconfiguration.attachObjectToConfiguration(n,(r,)) 
                return
            
            #no route or no vlan so default route if there is a default route otherwise no route no vlan
            
            t = determineIpType(n.address)
            
            if t==4 and bigipconfiguration.hasDefaultRoute4==True:
                r=bigipconfiguration.getDefaultRouteByRD(n.rd, 4)
            elif t==6 and bigipconfiguration.hasDefaultRoute6==True:
                r=bigipconfiguration.getDefaultRouteByRD(n.rd, 6)
            
            if not r==None:
                n.vlan=None
                n.route=r
                bigipconfiguration.attachObjectToConfiguration(n,(r,))
            else:
                n.vlan=None
                n.route=None
                bigipconfiguration.attachObjectToConfiguration(n)
            
            return
     
    def audit():
        print('[*] Auditing configuration - Nodes.')
        for n in bigipconfiguration.nodes:
            
            #is node used in none of the pools
            if len(n.pools)==0:
                bigipconfiguration.attachObjectToComment(n, 401, True)
   
    def postProcess(self):
        
        #We link Vs directly to nodes for easier rendering in displayed tables.
        if len(self.pools)!=0:
            for p in self.pools:
                self.virtuals += p.virtuals
            self.counterVirtuals= len(self.virtuals)
        
        
        self.counterPools = len(self.pools)
        #print('number of pools attached to this node: %i' % self.counterPools  )
        if self.counterPools==0:
            bigipconfiguration.attachOrphanObjectToConfiguration(self)
            
        else:
            if determineIpType(self.address)==4:        
                if not bigipconfiguration.hasDefaultRoute4:
                    if self.vlan==None and self.route==None:
                        bigipconfiguration.attachOrphanObjectToConfiguration(self)
                        
            
            elif determineIpType(self.address)==6:        
                if not bigipconfiguration.hasDefaultRoute6:
                    if self.vlan==None and self.route==None:
                        bigipconfiguration.attachOrphanObjectToConfiguration(self)
            
class pool(ltmObject):

    def __init__(self, name='none', counterVirtuals = 0, comments=None):
        ltmObject.__init__(self, name, comments)
        self.nodes = []
        self.virtuals = [] 
        self.vlans = []
        
        self.counterVirtuals = counterVirtuals

    def process(config):
        global bigipconfiguration
        
        p = pool()
        r=None

        #####################################
        # Extract info from pool from config
        #####################################

        name =re.search('(^ltm pool (.*))',config)
        if name:
            p.name=isolate(name.group(0).replace('ltm pool', ''))

        address =re.findall('([\s]*address.*)',config)

        #######################################
        # Attach pool to config and to its VLAN
        #######################################        
        
        for a in address:
            
            r = bigipconfiguration.getRdByID(extractRD(a))
            a = isolate(a.replace('address', ''))

            for n in bigipconfiguration.nodes:
                if n.address==a and n.rd.id==r.id:
                    n.pools.append(p)
                    p.nodes.append(n)
                    if not n.vlan in p.vlans:
                        p.vlans.append(n.vlan)

        bigipconfiguration.attachObjectToConfiguration(p)
        
        ##################################################
        # Attach pool to routes that use pool for next hop
        ##################################################
        
        for r in bigipconfiguration.routes:
            if not r.pool==None:
                if r.pool.name==p.name:
                    r.pool=p
                    #stored as a string so not working.
                    r.egressvlan=p.vlans

    def getVlanList(self='none'):
        vlans=''
        #optimize so no loop everytime tags are retrieved.
        for n in self.nodes:
            if not n.vlan==None:
                vlans+= n.vlan.tag
                vlans+= ' '
            else:
                vlans+= 'none\n'
        words = vlans.split()
        vlans =' '.join(sorted(set(words), key=words.index))
        if vlans=='':
            vlans='none\n'
        return vlans

    def audit():
        print('[*] Auditing configuration - Pools.')
        
        for p in bigipconfiguration.pools:
            #print('POOL:', p.name) 

            #Empty pools
            if len(p.nodes)==0:
                bigipconfiguration.attachObjectToComment(p, 501, True)
        
            #Unnattached pools
            if len(p.virtuals)==0:
                bigipconfiguration.attachObjectToComment(p, 504, True)
                
            #Nodes on multiple VLANs and routed.
            v = p.getVlanList().split()
            if ("none" in v):
                v.remove("none")
                if len(v)==1:
                    #Some nodes are routed all other nodes are on same 1 vlan    
                    bigipconfiguration.attachObjectToComment(p, 503)
                if len(v)>1:
                    #Some nodes are routed all other nodes are on multiple vlans  
                    bigipconfiguration.attachObjectToComment(p, 503)
                    bigipconfiguration.attachObjectToComment(p, 502)
            else:
                #No nodes are routed, all nodes are on multiple vlans
                if len(v)>1:
                    bigipconfiguration.attachObjectToComment(p, 502)

    def postProcess(self):
        self.counterVirtuals = len(self.virtuals)
        #print('number of virtuals attached to virtuals: %i' % self.counterVirtuals  )
        if self.counterVirtuals==0:
            bigipconfiguration.attachOrphanObjectToConfiguration(self)
            
class virtual(ltmObject):

    def __init__(self, name='none', address='none', counterNodes = 0, comments=None):
        ltmObject.__init__(self, name, comments)

        self.address: str = address
        self.vlan = None
        self.pool = None
        self.nodes = []
        self.counterNodes=counterNodes

    def process(config):
        global bigipconfiguration
        v = virtual()    
        p = pool()

        #######################################
        # Extract info from virtual from config
        #######################################

        name =re.search('(^ltm virtual (.*))',config)
        if name:
            v.name=isolate(name.group(0).replace('ltm virtual', ''))

        mask =re.search('([\s]*mask (.*))',config)
        if mask:
            mask=isolate(mask.group(0).replace('mask', ''))
        if mask == 'any':
            mask ='0.0.0.0'
        if mask=='any6':
            mask='0'

        address =re.search('([\s]destination (.*))',config)
        rdid=str(extractRD(str(address)))
        if address:
            a=address.group(0)
            b=a.replace('destination', '')
            c=isolate(b)
            d = re.search('\.[0-9]+$',c)
            if d !=None:
                #ipv6
                e=c.split('/')
                ee=e[2]
                f=''
                if ee=='':
                    f==e[1]
                else:
                    eee=ee.split('.')
                    f=eee[0]
            else:
                e=c
                f=e.split('/')[2].split(':')[0]
        
            f=isolate(f)
        else:
            #some Vs do not have ip addresses "traffic-matching-criteria "
            f='225.5.5.5'
            mask='32'
            
        if f=='any':
            f='0.0.0.0'
        
        if f=='any6':
            f='::/0'
         
        if determineIpType(f)==4:
            v.address=f
            v.address+='/'
            v.address+=mask 
            v.address=ipaddress.IPv4Interface(v.address)
        elif determineIpType(f)==6:
            v.address=f
            v.address=ipaddress.IPv6Interface(v.address)
        else:
            #print('error - unknown IP version on this VS')
            v.address=f

        npool =re.search('([\s]*pool (.*))',config)
        if npool:
            npool=isolate(npool.group(0).replace('pool /', '/'))
            for p in bigipconfiguration.pools:
                if npool == p.name:
                    v.pool = p
                    break
                    
        #############################################################
        # Attach virtual to vlan and to pool, add VS to configuration
        #############################################################

        r=bigipconfiguration.getRdByID(rdid)
        w=r.getVlanByAddress(str(v.address))
        v.vlan=w
        
        #bigipconfiguration.attachObjectToConfiguration(v)
        
        if not w == None and not p == None:
            bigipconfiguration.attachObjectToConfiguration(v,(w,p))
        elif not w == None and p == None:
            bigipconfiguration.attachObjectToConfiguration(v,(w,))
        elif w == None and not p == None:
            bigipconfiguration.attachObjectToConfiguration(v,(p,))
        else:
            print('error')

    def audit():
        print('[*] Auditing configuration - Virtuals.')      
        for v in bigipconfiguration.virtuals:
            
            #No pool attached to Virtual
            if v.pool==None: #Empty
                bigipconfiguration.attachObjectToComment(v, 604, True)
                
            elif type(v.pool)==pool:
                if v.vlan!=None:
                    #Virtual is on the same vlan as pool members:        
                    if v.vlan.tag==v.pool.getVlanList():
                        #print('Virtual %s and pool members are on the same vlan %s | %s ' % (v.name, v.vlan.tag, v.pool.getVlanList())  )
                        bigipconfiguration.attachObjectToComment(v, 601)
                        
                    #Virtual is on the same vlan as some of the pool members:        
                    elif ( v.vlan.tag!=v.pool.getVlanList() and (v.vlan.tag in v.pool.getVlanList())):
                        #print('Virtual %s and some pool members are on the same vlan %s | %s ' % (v.name, v.vlan.tag, v.pool.getVlanList())  )
                        bigipconfiguration.attachObjectToComment(v, 602)
                        
                    #Virtual is on a completely different vlan than the pool members:        
                    elif ( v.vlan.tag!=v.pool.getVlanList() and not(v.vlan.tag in v.pool.getVlanList())):
                        #print('Virtual %s is on a completely different vlan than all the pool members %s | %s ' % (v.name, v.vlan.tag, v.pool.getVlanList())  )            
                        bigipconfiguration.attachObjectToComment(v, 603)   
                else:
                    #No virtual doesn't belong to any of the vlan's subnet
                    pass

    def postProcess(self):
        
        #We link nodes directly to Vs for easier rendering in displayed tables.
        if self.pool!=None:
            p = self.pool
            for n in p.nodes:
                self.nodes.append(n)
            self.counterNodes= len(self.nodes)
                                      
        if self.pool==None:
            bigipconfiguration.attachOrphanObjectToConfiguration(self)

######################
# Container
######################

class orphans:

    def __init__(self='none' ):
        name = "orphans"
        self.vlans = []
        self.selfips = []
        self.routes = []
        self.nodes = []
        self.pools = []
        self.virtuals = []
 
class configuration:

    def __init__(self):
        self.name = "To Be Aranged" #bigipbaseName
        self.hostname = None
        self.isHA = False
        self.trafficGroups =[]
        self.isIPv4 = False
        self.isIPv6 = False
        self.hasRouteDomains=False
        self.hasDefaultRoute4 =False
        self.hasDefaultRoute6 =False
        self.routeDomains = []
        self.vlans = []
        self.selfips = []
        self.routes = []
        self.nodes = []
        self.pools = []
        self.virtuals = []
        self.orphans = orphans()
        self.comments = []
        self.orphan = False #useless but prevent crash when scanning orphan routes.

    def parse(file, regexStart, regexEnd, ltmObjectType):
        print('[*] Parsing %s for %s - ' % (file.name, ltmObjectType.__name__ ), end='' )
        global bigipconfiguration

        found=False

        counter = 0

        file.seek(0)
        config = ''
    
        patternStart = re.compile(regexStart)
        patternEnd = re.compile(regexEnd)

        for i, line in enumerate(file):
           if patternStart.search(line):
                config = line
                for j, line in enumerate(file, start=i):
                    config += line 
                    if patternEnd.search(line):
                        found=True
                        counter += 1
                        ltmObjectType.process(config)
                        break
        print(counter)
    
    def adjustVlansRD():    
        #We scan the vlan list we have discovered for vlan that have not been added to an RD yet
        #And we add them to the right RD.                    
    
        for ro in bigipconfiguration.routeDomains:
            for vl in bigipconfiguration.vlans:
                if ro.isVlanInRDVlanList(str(vl.name)) and ro.getVlanByName(str(vl.name))==None:
                    #print('vlan - ', vl.name)
                    ro.vlans.append(vl)
                    vl.rd=ro 
    
    def getVlanByName(self, name):
        for v in self.vlans:
            if v.name==name:
                return v

    def getRdByID(self, id):
        for r in self.routeDomains:
            if r.id==id:
                return r
        return None

    def getRdByName(self, name):
        for r in self.routeDomains:
            if r.name==name:
                return r

    def attachObjectToConfiguration(self, ltmObject1, ltmObjectTuple2=None):

        configurationObjectsArray = objectTypeToConfigurationArray(type(ltmObject1), bigipconfiguration)
        configurationObjectsArray.append(copy.copy(ltmObject1))
        
        m=(type(ltmObject1)).__name__
        
        if ltmObjectTuple2!=None:
            
            for n in ltmObjectTuple2:
                
                if type(n)==vlan:

                    if m=='node':
                        t=determineIpType(ltmObject1.address)
                        if t==4:
                            o=getattribute(n.getVlanNetworkFromAddress(ltmObject1.address,4), 'nodes')
                        if t==6:
                            o=getattribute(n.getVlanNetworkFromAddress(ltmObject1.address,6), 'nodes')
                    elif m=='pool':
                        pass
                    elif m=='virtual':
                        t=determineIpType(ltmObject1.address)
                        if t==4:
                            o=getattribute(n.getVlanNetworkFromAddress(ltmObject1.address,4), 'virtuals')
                        if t==6:
                            o=getattribute(n.getVlanNetworkFromAddress(ltmObject1.address,6), 'virtuals')
                    elif m=='selfip':
                        t=determineIpType(ltmObject1.address)
                        if t==4:
                            o=getattribute(n.getVlanNetworkFromAddress(ltmObject1.address, 4),'selfips')
                        if t==6:
                            o=getattribute(n.getVlanNetworkFromAddress(ltmObject1.address, 6),'selfips')
                    
                elif type(n)==pool:
                    
                    if m=='node':
                        pass
                    elif m=='pool':
                        pass
                    elif m=='virtual':
                        o=getattribute(n,'virtuals')
                    
                elif type(n)==route:
                    
                    if m=='node':
                        o=getattribute(n,'nodes')
                        pass
                    elif m=='pool':
                        pass
                    elif m=='virtual':
                        pass
                    
                elif type(n)==virtual:
                    if m=='node':
                        pass
                    elif m=='pool':
                        pass
                    elif m=='virtual':
                        pass

                else:
                    print('error')
                
                o.append(configurationObjectsArray[-1])

    def attachOrphanObjectToConfiguration(self, ltmObject1):
        ltmObject1.orphan=True
        configurationOrphanObjectsArray = objectTypeToConfigurationArray(type(ltmObject1), bigipconfiguration.orphans)        
        #configurationOrphanObjectsArray.append(copy.copy(ltmObject1))
        configurationOrphanObjectsArray.append(ltmObject1)

    def attachObjectToComment(self, ltmObject, id, isOrphan=False):
        
        found1=False
        found2=False
        
        for c in ltmObject.comments:
            if c==result.comments[id]:
                found1=True
                
        if found1==False:       
            ltmObject.comments.append(result.comments[id])
             
        for o in result.comments[id].objects: 
            if o()==ltmObject:
                found2=True
                
        if found2==False:  
            result.comments[id].objects.append(weakref.ref(ltmObject))

    def getRouteByRdAndAddress(self, d, address):
        
        t=determineIpType(address)
        if t==4:
            for r in self.routes:
                if r.destination.rd == d and not r.destination.network == '0.0.0.0/0':
                    if determineIpType(r.destination.network)==4:
                        if ipaddress.IPv4Network(address).subnet_of(ipaddress.IPv4Network(r.destination.network)):
                            return r
        elif t==6:
            for r in self.routes:
                if r.destination.rd == d and not r.destination.network == '::': #to be verified
                    if determineIpType(r.destination.network)==6:
                        if ipaddress.IPv6Network(address).subnet_of(ipaddress.IPv4Network(r.destination.network)):
                            return r
        else:
            return 'error'                 

    def getDefaultRouteByRD(self, d, type):
        
        if type==4:
            for r in self.routes:
                if r.destination.rd == d and r.destination.network == '0.0.0.0/0':
                    return r
        elif type==6:
            for r in self.routes:
                if r.destination.rd == d and r.destination.network == '::': #to be verified
                    return r    
        else:
            return 'error'  

    def sysInfo():
        
        print(underlinize(bolderize('[*] System Information\n' )))
        
        print('[+] Hostname:',bigipconfiguration.hostname)
        print('[+] HA system:',bigipconfiguration.isHA)
        print('[+] IPv4 enabled:',bigipconfiguration.isIPv4)
        print('[+] IPv4 default route:',bigipconfiguration.hasDefaultRoute4)
        print('[+] IPv6 enabled:',bigipconfiguration.isIPv6)
        print('[+] IPv6 default route:',bigipconfiguration.hasDefaultRoute6)
        print('[+] Multiple Route Domains configured :',bigipconfiguration.hasRouteDomains)
        print("")

    def postProcess(ltmObjectType1):
        
        a = objectTypeToConfigurationArray(ltmObjectType1, bigipconfiguration)
        for o in a:
            o.postProcess()       

class output:

    def getRouteDomain(object):
        r=''
        if type(object)==selfip:
            if object.vlan!=None:
                r = getattribute(getattribute(getattribute(object, 'vlan'),'rd'),'id')
            else:
                r = '0'
        elif type(object)==gw:
            if object.vlan!=None:
                r = getattribute(getattribute(getattribute(object, 'vlan'),'rd'),'id')
            else:
                r = '0'
        elif type(object)==destination:
            r = getattribute(getattribute(object,'rd'),'id')
        elif type(object)==node:
            r = str(object.rd.id)
            r = getattribute(getattribute(object,'rd'),'id')
        elif type(object)==virtual:
            if object.vlan!=None:
                r = getattribute(getattribute(getattribute(object, 'vlan'),'rd'),'id')
            else:
                r = '0'
        elif type(object)==vlan:
            r = getattribute(getattribute(object,'rd'),'id')
            
        elif type(object)==network:
            r = getattribute(getattribute(getattribute(object, 'vlan'),'rd'),'id')
            
        if r== None:
            r='0'

        return r

    def insertRouteDomain(object, field):
        s=''
        
        if object==None:
            return 'None\n'
        
        if type(object)==ltmObject:
            return 'none\n' #required for the proper formatting.

        if field in ('network','address','gw','network4','network6', 'prefix'):
            t=getattribute(object, field)
            if type(t)==list:
                for p in t:
                    c=str(p)
                    if '/' in c:
                        s+=str(c).replace('/','%'+str(output.getRouteDomain(object))+'/')+'\n'
                    else:
                        s+=str(c)+'%'+str(output.getRouteDomain(object))+'\n'
            else:
                if '/' in str(t):
                    s+=str(t).replace('/','%'+str(output.getRouteDomain(object))+'/')+'\n'
                else:
                    if not t==None:
                        if not determineIpType(t)==0:
                            s+=str(t)+'%'+str(output.getRouteDomain(object))+'\n'
                        else:
                            s+=str(t)
                    else:
                        s+='None'
        else:
            s+=str(getattribute(object, field))+'\n'
        return s#.replace('%0','')# we dont display %0 for default rd

    def formatCell(criticality, atomObject, fields, location=None, formatting=True):#=["name"]):
            
        if location==None:
            location=[]

        s=''

        if not isinstance(atomObject, list):
            #if our field_name is not a tuple we tranform it into a 1 element tuple.
            atomObject=[atomObject]

        if not isinstance(location, list):
            #if our field_name is not a tuple we tranform it into a 1 element tuple.
            location=[location]
            
        if not isinstance(fields, list):
            #if our field_name is not a tuple we tranform it into a 1 element tuple.
            fields=[fields]
        
        for atom in atomObject:
            
            #We set the network type we want to display next to our node
            netType=''
            if type(atom)==node and 'networkX' in location:     #add pool as a type(ATOM)
                
                if determineIpType(atom.address)==4:
                    netType='network4'
                elif determineIpType(atom.address)==6:
                    netType='network6'
                    
                for i in range(len(location)):
                    if location[i] == 'networkX':
                        location[i] = netType
            
            if len(location)==0:
                for f in fields:
                    s+=output.insertRouteDomain(atom,f)
            
            #Recursion
            elif len(location)>0:
                c = getattribute(atom, location[0])
                if type(c)==list:
                    for a in c:
                        s+=output.formatCell(criticality, a, fields, location[1:], formatting)
                        s+='\n'
                else:
                    s+=output.formatCell(criticality, c, fields, location[1:], formatting)
                    s+='\n'
        
        if s=='':
            s='None'

        if formatting==True:
            return (colorize(str(s.rstrip("\n")),criticality))           
        else:
            return str(s.rstrip("\n"))

    def display(configurationObjectsArray, view=view.literal):

        print()

        if len(configurationObjectsArray)==0:
            return
    
        print('[*] Configuration - %s.' % type(configurationObjectsArray[0]).__name__)
               
        if(view==view.literal):
                
            if type(configurationObjectsArray[0]).__name__=="rd":
                
                field_names   = ["RD Name",   "RD ID",   "Vlans"] 
                fieldNames      = ["name",      "id",      ("vlans","name")]

                output.render(configurationObjectsArray, fieldNames, field_names, "RD ID")
                
            elif type(configurationObjectsArray[0]).__name__=="vlan":
                
                field_names   = ["VLAN Name",    "VLAN Tag", "Subnet 4"]
                fieldNames      = ["name",         "tag",      ("network4","prefix")]

                if bigipconfiguration.isIPv4:
                    output.render(configurationObjectsArray, fieldNames, field_names, "VLAN Tag")
                               
                field_names   = ["VLAN Name",    "VLAN Tag", "Subnet 6" ]
                fieldNames      = ["name",         "tag",      ("network6","prefix")]

                if bigipconfiguration.isIPv6:
                    output.render(configurationObjectsArray, fieldNames, field_names, "VLAN Tag")
                                
            elif type(configurationObjectsArray[0]).__name__=="selfip":

                field_names   = ["SELF Name",    "SELF Address",  "SELF Type",    "SELF VLAN Tag",    "SELF VLAN Name"]            
                fieldNames      = ["name",         "address",       "kind",         ("vlan","tag"),     ("vlan","name")  ]

                output.render(configurationObjectsArray, fieldNames, field_names, "SELF VLAN Tag")

            elif type(configurationObjectsArray[0]).__name__=="route":
                field_names   = ["Route Name",   "Destination",               "via Next-Hop ?",   "via Interface ?",      "via Pool ?",       "Egress VLAN"  ]
                fieldNames      = ["name",         ("destination", "network"),  ("gw","address"),   ("interface","name"),   ("pool", "name"),   ("egressvlan","tag")]

                output.render(configurationObjectsArray, fieldNames, field_names, "Destination")

            elif type(configurationObjectsArray[0]).__name__=="node":
                field_names   = ["Node Name",    "Node Address", "Node VLAN",        "Route Name"]          
                fieldNames      = ["name",         "address",      ("vlan","tag"),     ("route","name")]

                output.render(configurationObjectsArray, fieldNames, field_names, "Node VLAN")
                
            elif type(configurationObjectsArray[0]).__name__=="pool":
                field_names   = ["Pool Name",    "Node Name",        "Node Address",          "Node VLAN network",                       "Node VLAN tag",              "Node Route"               ]
                fieldNames      = ["name",         ("nodes","name"),   ("nodes", "address"),    ("nodes", "vlan","networkX", "prefix"),    ("nodes", "vlan", "tag"),     ("nodes", "route", "name")]

                output.render(configurationObjectsArray, fieldNames, field_names, "Node VLAN tag")
                                
            elif type(configurationObjectsArray[0]).__name__=="virtual": 
                field_names   = ["Virtual Name",     "Virtual Address",  "VLAN",              "Pool Name",        "Pool VLANs"]
                fieldNames      = ["name",             "address",          ("vlan", "tag"),     ("pool","name"),    ("pool","vlans","tag")]

                output.render(configurationObjectsArray, fieldNames, field_names, "VLAN")
                
            else:
                return
            
        elif(view==view.insights): 
              
            if type(configurationObjectsArray[0]).__name__=="rd":
                noInfo()
                return    
                  
            elif type(configurationObjectsArray[0]).__name__=="vlan":
                
                field_names   = ["VLAN Name",    "VLAN Tag", "# Virtuals",       "# Nodes"]
                fieldNames      = ["name",         "tag",      "counterVirtualsTotal",   "counterNodesTotal"]
                output.render(configurationObjectsArray, fieldNames, field_names)

            elif type(configurationObjectsArray[0]).__name__=="selfip":
                noInfo()
                return    

            elif type(configurationObjectsArray[0]).__name__=="route":
                field_names   = ["Route Name",   "Destination",               "overlapped by"]
                fieldNames      = ["name",         ("destination", "network"),  ("overlap_vlan","name")]
                output.render(configurationObjectsArray, fieldNames, field_names)

            elif type(configurationObjectsArray[0]).__name__=="node":
                noInfo()
                return    
                
            elif type(configurationObjectsArray[0]).__name__=="pool":
                noInfo()
                return    
                
            elif type(configurationObjectsArray[0]).__name__=="virtual": 
                noInfo()
                return    
                
        elif(view==view.reverse): 
              
            if type(configurationObjectsArray[0]).__name__=="rd":
                noInfo()
                return    
                  
            elif type(configurationObjectsArray[0]).__name__=="vlan":
                field_names   = ["VLAN Name",    "VLAN Tag", "Nodes 4",                       "Nodes 4 address",                "# Nodes 4",        "Virtuals 4",                     "Virtuals 4 address",                 "# Virtuals 4"]
                fieldNames      = ["name",         "tag",      ("network4","nodes", "name"),    ("network4","nodes", "address"),    "counterNodes4",    ("network4","virtuals", "name"),  ("network4","virtuals", "address"),     "counterVirtuals4"]
                if bigipconfiguration.isIPv4:
                    output.render(configurationObjectsArray, fieldNames, field_names)
                
                field_names   = ["VLAN Name",    "VLAN Tag", "Nodes 6",                       "Nodes 6 address",                "# Nodes 6",        "Virtuals 6",                     "Virtuals 6 address",                 "# Virtuals 6"]
                fieldNames      = ["name",         "tag",      ("network6","nodes", "name"),    ("network6","nodes", "address"),    "counterNodes6",    ("network6","virtuals", "name"),  ("network6","virtuals", "address"),     "counterVirtuals6"]
                if bigipconfiguration.isIPv6:
                    output.render(configurationObjectsArray, fieldNames, field_names)
                
            elif type(configurationObjectsArray[0]).__name__=="selfip":
                noInfo()
                return  

            elif type(configurationObjectsArray[0]).__name__=="route":
                field_names   = ["Route Name",   "Destination",               "Nodes ",             "Nodes address",          "# Nodes "]
                fieldNames      = ["name",         ("destination", "network"),  ("nodes", "name"),    ("nodes", "address"),     "counterNodes"]
                output.render(configurationObjectsArray, fieldNames, field_names)
                
            elif type(configurationObjectsArray[0]).__name__=="node":
                field_names   = ["Node Name",    "Node Address", "Pool Name",     "# Pools",              "Virtual Name",          "# Virtuals"]          
                fieldNames      = ["name",         "address",      ("pools","name"), ("counterPools"),      ("virtuals", "name"),    ("counterVirtuals")]
                output.render(configurationObjectsArray, fieldNames, field_names)
                
            elif type(configurationObjectsArray[0]).__name__=="pool":
                field_names   = ["Pool Name",    "Pool VLANs",            "Virtual Name",        "Virtual Address",               "# Virtuals"]
                fieldNames      = ["name",         ("vlans", "tag"),        ("virtuals","name"),   ("virtuals", "vlan", "tag"),     "counterVirtuals"]
                output.render(configurationObjectsArray, fieldNames, field_names)
                
            elif type(configurationObjectsArray[0]).__name__=="virtual": 
                field_names   = ["Virtual Name",     "Virtual Address",  "Node Name",                 "Node Address",                 "# Nodes"]
                fieldNames      = ["name",             "address",          ("nodes", "name"),           ("nodes", "address"),           ("counterNodes")]
                output.render(configurationObjectsArray, fieldNames, field_names)
                
        elif(view==view.wide): #empty for future development
                
            if type(configurationObjectsArray[0]).__name__=="rd":
                noInfo()
                return  
                
            elif type(configurationObjectsArray[0]).__name__=="vlan":
                noInfo()
                return  
                
            elif type(configurationObjectsArray[0]).__name__=="selfip":
                noInfo()
                return  

            elif type(configurationObjectsArray[0]).__name__=="route":
                noInfo()
                return  

            elif type(configurationObjectsArray[0]).__name__=="node":
                noInfo()
                return  
                
            elif type(configurationObjectsArray[0]).__name__=="pool":
                noInfo()
                return  
            
            elif type(configurationObjectsArray[0]).__name__=="virtual": 
                noInfo()
                return  
            
            else:
                return
 
    def render(configurationObjectsArray, fieldNames, field_names, sortByField=None):
        
        t = PrettyTable()
        t.field_names=field_names

        for o in configurationObjectsArray:
            
            criticality=results.getHighestPriorityComment(o.comments)
            valueList = []

            fieldLocations=[]
            for f in fieldNames:
                fieldLocations=[]
                if not isinstance(f,tuple):
                    f=(f,)
                                              
                for e in f:
                    if e!=f[-1]:
                        fieldLocations.append(e)    
                columnFields=f[-1]
                res=output.formatCell(criticality, o, columnFields, fieldLocations)
                            

                #deduplicate vlan list in virtual output
                if columnFields=='tag' and type(o)==virtual:
                    res2 = res.split()
                    res = (" ".join(sorted(set(res2), key=res2.index))).replace(' ','\n')
                    pass
                
                valueList.append(res)
                fieldLocations.clear()

                for cell in valueList:
                    if "\n" in cell:
                        t.hrules=ALL
                        break
                      
            t.add_row(valueList)
        t.align = "l"
        t.sortby = sortByField
        print(t.get_string())   
        print('')
        if xlsxExport==True:
            output.render_xls(configurationObjectsArray, fieldNames, field_names, sortByField)
     
    def render_xls(configurationObjectsArray, fieldNames, field_names, sortByField=None):
        
        global targetXlsxFile

        worksheet = targetXlsxFile.add_worksheet(type(configurationObjectsArray[0]).__name__)
        #header
        x=0
        y=0
        
        fieldNames.append(("comments","description"))
        field_names.append("comments")
        
        dict_field_names=dict.fromkeys(field_names,0)
        
        t = PrettyTable()
        t.align = "l"
        t.field_names=field_names
        
        cell_format_header = targetXlsxFile.add_format()
        cell_format_header.set_bold()
        cell_format_header.set_bg_color('gray')
        cell_format_header.set_border()
        cell_format_header.set_align('top')
        
        for u in t.field_names:
            worksheet.write(y, x, u,cell_format_header)
            x+=1
        
        #content
        x=0    
        y=1
        
        for o in configurationObjectsArray:

            cell_height=0

            c=results.getHighestPriorityComment(o.comments)

            cell_format = targetXlsxFile.add_format()
            cell_format.set_bg_color('#C0C0C0')
            cell_format.set_border()
            cell_format.set_align('top')
            cell_format.set_text_wrap()
            
            if(c==criticality.error):
                cell_format.set_font_color('red')                
            elif(c==criticality.warning):
                cell_format.set_font_color('yellow')
            elif(c==criticality.info):
                cell_format.set_font_color('green')

            valueList = []
            
            fieldLocations=[]
            for f in fieldNames:
                
                #Generate table row
                fieldLocations=[]
                if not isinstance(f,tuple):
                    f=(f,)
                                              
                for e in f:
                    if e!=f[-1]:
                        fieldLocations.append(e)    
                columnFields=f[-1]
                res=output.formatCell(c, o, columnFields, fieldLocations, False)
                tmp_res = res.splitlines()

                #deduplicate vlan list in virtual output
                if columnFields=='tag' and type(o)==virtual:
                    res2 = res.split()
                    res = (" ".join(sorted(set(res2), key=res2.index))).replace(' ','\n')
                    pass

                if len(tmp_res)>cell_height:
                    cell_height=len(tmp_res)

                if columnFields=='description':
                    res=unformat(res) 

                #We adjust the column sizes to match the width of the widest cell:
                if len(res)>dict_field_names[t.field_names[x]]:
                    if "\n" in res:
                        tmp_res = res.splitlines()
                        for r in tmp_res:
                            if len(r)>dict_field_names[t.field_names[x]]:
                                dict_field_names[t.field_names[x]]=len(r)
                    else:
                        dict_field_names[t.field_names[x]]=len(res)
                    if dict_field_names[t.field_names[x]] > len (t.field_names[x]):
                        worksheet.set_column(x,x,dict_field_names[t.field_names[x]]+5)
                    else:
                        worksheet.set_column(x,x,(len(t.field_names[x]))*1.5)
                        
                fieldLocations.clear()
                
                #We adjust the row sizes to match the size of the largest cell on that row:
                if f==fieldNames[-1]:
                    worksheet.set_row(y,15*cell_height)

                worksheet.write(y, x, res,cell_format)
                x+=1
            x=0
            y+=1
        pass
            
class results:
    
    def __init__(self, comments=None):
        self.comments = {}
      
    def tabulateComments(self, IDstart, IDstop, mode=mode.brief, orphan=False):
        
        isEmtpy=True
    
        numberOfColumns=4
        numberOfRows=0
        placeholder=[]
        
        for key in range(IDstart, IDstop):
            
            try:
                self.comments[key]
            except KeyError:
                continue
            
            placeholder=[]
            
            for object in self.comments[key].objects:
                if not orphan:
                    placeholder.append(object().name)
                else:
                    if object().orphan:
                        placeholder.append(object().name)
            
            if(len(placeholder)>0):
                
                isEmtpy=False
                
                print(flag(self.comments[key].priority),'-',unformat(self.comments[key].description),' (%i objects)' % len(placeholder))
                if mode>mode.brief:
                                    
                    table = PrettyTable(border=False, header=False, align = "l") 
                    
                    numberOfRows=len(placeholder)//numberOfColumns
                    objectList=chunks(placeholder,numberOfColumns) 

                    tmp=[]
                    for list in objectList:
                        if numberOfRows>0:
                            while len(list)<numberOfColumns:
                                list.append('')
                        for cell in list:
                            tmp.append(colorize(cell, 94))
                        table.add_row(tmp)
                        tmp=[]
                    table.align = "l"
                    print(table.get_string())
            
        if isEmtpy==True:
            print('No information available at this time')
                                 
    def display(self, objectArray, ltmObjectType1, mode=mode.brief, view=view.literal ):
        
        print("\n\r")
        
        a=objectTypeToConfigurationArray(ltmObjectType1, objectArray)
        
        if ltmObjectType1==vlan:
            commentLowID = 10
            commentHighID = 131
        elif ltmObjectType1==selfip:
            commentLowID = 201
            commentHighID = 228        
        elif ltmObjectType1==route:
            commentLowID = 301
            commentHighID = 304       
        elif ltmObjectType1==node:
            commentLowID = 401
            commentHighID = 404        
        elif ltmObjectType1==pool:
            commentLowID = 501
            commentHighID = 505  
        elif ltmObjectType1==virtual:
            commentLowID = 601
            commentHighID = 605        
        elif ltmObjectType1==rd:
            commentLowID = 701
            commentHighID = 701  
                
        #print()
        
        if objectArray==bigipconfiguration:        
            print(underlinize(bolderize('[*] %s Audit Results\n' % ltmObjectType1.__name__.upper())))
            self.tabulateComments(commentLowID, commentHighID, mode, False)
            #print("\n\r") 
            
        elif objectArray==bigipconfiguration.orphans:
            print(underlinize(bolderize('[*] %s Orphan Results\n' % ltmObjectType1.__name__.upper())))
            self.tabulateComments(commentLowID, commentHighID, mode, True)
            #print("\n\r")
            
        if(mode==mode.extended):
            output.display(a, view)

    def getHighestPriorityComment(comments):
        p=100
        for c in comments:
            if (c.priority<p):
                p=c.priority
        return p 
       
######################
# Excel
######################   

def createXlsFileName():
    
    global targetXlsxFile
    if len(bigipList)>0:
        p=Path(bigipList[0])
        return str(bigipList[0])+'.xlsx'
    elif len(bigipbaseList)>0:
        p=Path(bigipbaseList[0])
        return str(bigipbaseList[0])+'.xlsx'
    else:
        return "5drss.xlsx"       
             
######################
# App
######################   
    
global bigipconfiguration
bigipconfiguration = configuration()

global result
result = results()

global displayMode
displayMode=mode.extended

global tableMode
tableMode=view.literal
  
def cli():
    global bigipbaseList, bigipList, bigipbaseName, bigipName, displayMode, tableMode, xlsxExport

    # Create the parser
    cli_parser = argparse.ArgumentParser(description='Extract L3 insights from a bigip.conf and a bigip_base.conf')
    
    # Add the arguments
    #https://support.f5.com/csp/article/K26582310
    cli_parser.add_argument('-b', '--base', type=str, metavar='\b', required=False, help='Path to the base configuration file(s), separate partiton files using commas without any space (default: bigip_base.conf)')
    cli_parser.add_argument('-t', '--traffic', type=str, metavar='\b', required=False, help='Path to the configuration file(s), separate partiton files using commas without any space (default: bigip.conf)')
    cli_parser.add_argument('-f', '--folder', type=str, metavar='\b', required=False, help='Path to a folder containing configuration file(s) (default: . )')
    cli_parser.add_argument('-o', '--output', type=str, metavar='\b', required=False, help='Output Mode (brief, full, extended)')
    cli_parser.add_argument('-v', '--view', type=str, metavar='\b', required=False, help='Layout of tables when using Extended output (literal, insights, reverse)')
    cli_parser.add_argument('-x', '--export', required=False, action='store_true', help='Export output to a .xlsx file')

    args = cli_parser.parse_args()
    
    if args.base:
        bigipbaseList = args.base.split(',')
    else:
        bigipbaseList.append('bigip_base.conf')
        #bigipbaseList.append('../5health/17220229_bigip_base.conf')
        
    if args.traffic:
        bigipList = args.traffic.split(',')
    else:
        bigipList.append('bigip.conf')
        #bigipList.append('../5health/17220229_bigip.conf')
        
    if args.folder:
        if args.base or args.traffic:
            print('Syntax error: Use base(-b) with traffic(-t) OR folder(-f) but not both at the same time.')
            sys.exit()
        else:
            buildBigipFileListFromPath(args.folder) 
        
    if args.output:
        if args.output=='brief':
            displayMode=mode.brief
        elif args.output=='full':
            displayMode=mode.full
        elif args.output=='extended':
            displayMode=mode.extended
        else:
            print("Invalid Output mode %s" % args.output)
                
    if args.view:
        if args.view=='literal':
            tableMode=view.literal
        elif args.view=='insights':
            tableMode=view.insights
        elif args.view=='reverse':
            tableMode=view.reverse
        else:
            print("Invalid Layout mode %s" % args.layout)       
              
    if args.export==True:
        createXlsFileName()
        xlsxExport=True
                  
def main():
    
    cli()
    comment.populate()
    
    global targetXlsxFile
       
    if xlsxExport==True:
        targetXlsxFile = xlsxwriter.Workbook(createXlsFileName())
    
    reorderBigipFileList()
    
    for bigipbaseFileName in bigipbaseList:
        #sys.stderr.write(bigipbaseFileName)
        #sys.stderr.write('\n')
        bigipbaseFile=checkBigipFile(bigipbaseFileName)
        configuration.parse(bigipbaseFile, '^sys global-settings {$', '^}$', globalSettings)
        configuration.parse(bigipbaseFile, '^cm device-group .* {$', '^}$', deviceGroup)
        configuration.parse(bigipbaseFile, '^net vlan .* {$', '^}$', vlan)
        configuration.parse(bigipbaseFile, '^net route-domain .* {$', '^}$', rd)
        configuration.adjustVlansRD()
        configuration.parse(bigipbaseFile, '^net self .* {$', '^}$', selfip)
    for bigipFileName in bigipList:
        #sys.stderr.write(bigipbaseFileName)
        #sys.stderr.write('\n')
        bigipFile=checkBigipFile(bigipFileName)
        configuration.parse(bigipFile, '^net route .* {$', '^}$', route)
        configuration.parse(bigipFile, '^ltm node .* {$', '^}$', node)
        configuration.parse(bigipFile, '^ltm pool .* {$', '^}$', pool)
        configuration.parse(bigipFile, '^ltm virtual .* {$', '^}$', virtual)
    print()

    vlan.audit()
    rd.audit()
    route.audit()
    selfip.audit()
    node.audit()
    pool.audit()
    virtual.audit()
    #print("\n\r")
    print()

    configuration.sysInfo()
       
    configuration.postProcess(vlan)
    configuration.postProcess(selfip)
    configuration.postProcess(route)
    configuration.postProcess(node)
    configuration.postProcess(pool)
    configuration.postProcess(virtual)
   
    #Results(Brief|Full|Extended)
    pause()
    result.display(bigipconfiguration, rd, displayMode, tableMode)
    pause()
    result.display(bigipconfiguration, vlan, displayMode, tableMode)
    pause()
    result.display(bigipconfiguration, selfip, displayMode, tableMode)
    pause()
    result.display(bigipconfiguration, route, displayMode, tableMode)
    pause()
    result.display(bigipconfiguration, node, displayMode, tableMode)
    pause()
    result.display(bigipconfiguration, pool, displayMode, tableMode)
    pause()
    result.display(bigipconfiguration, virtual, displayMode, tableMode)
    
    # pause()
    # result.display(bigipconfiguration.orphans, vlan, displayMode, tableMode)
    # pause()
    # result.display(bigipconfiguration.orphans, selfip, displayMode, tableMode)
    # pause()
    # result.display(bigipconfiguration.orphans, route, displayMode, tableMode)
    # pause()
    # result.display(bigipconfiguration.orphans, node, displayMode, tableMode)
    # pause()
    # result.display(bigipconfiguration.orphans, pool, displayMode, tableMode)
    # pause()
    # result.display(bigipconfiguration.orphans, virtual, displayMode, tableMode)
    if xlsxExport==True:
        targetXlsxFile.close()
        print('Data exported to ',createXlsFileName())

if __name__ == "__main__":
    main()
