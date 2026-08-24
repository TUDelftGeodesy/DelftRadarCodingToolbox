import os
import re
import json
import subprocess
import csv
import numpy as np
from collections import Counter
import geopandas as gpd
from pathlib import Path
from shapely.geometry import Polygon,Point
import xml.etree.ElementTree as ET
from time import asctime as timenow
import sarxarray
import matplotlib.pyplot as plt
from datetime import datetime,timedelta


# Custom
from gecoris import geoUtils


# Define constants
sc_n_pattern = '\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)'
speedOfLight = 299792458.0

  

def swathBurst(stackDir,stations,mode='slave'):
    
    '''
    The function finds the burst in which the stations are located according to the structure of the DORIS products
    
    To locate them the following steps are performed:
    
    (1) The shapeFile present in the datatake directory is read, 
        and the polygons describing the coverage of each burst are loaded
        
    (2) The stations are loaded and for each one the polygon in which they are included is found.
        
        
    (3) The burst in which the station is contained with the maximum distance with the borders is selected, 
        to avoid problems when loading the image, due to the inaccuracy of the footprints

    (4) The path of the metadata (.res) file is generated with the common burst
        
    '''
    
    # Load geometry data from swathburst_coverage shapefile
    shpPath = [p for p in Path(stackDir).rglob('../stackburst_coverage.shp')] 
    data = gpd.read_file(shpPath[0]) # Read the Shapefile using geopandas
    geometry = data.geometry
    

    # Iterate over bursts and stations
    swathburst = []
    dist = []
    for sb in range(len(data)):
        # Area of Coverage of current iteration
        AoC = geometry[sb]
            
        # for each target
        for station in stations:
            
            if station.descending:
                stationPoint = Point(station.descending.longitude*180/np.pi, station.descending.latitude*180/np.pi, station.descending.elevation)
            elif station.ascending:
                stationPoint = Point(station.ascending.longitude*180/np.pi, station.ascending.latitude*180/np.pi, station.ascending.elevation)
            else:
                raise Exception('Both ascending and descending are not active...')

            if AoC.contains(stationPoint):
                # print(station.id+": "+data.name[sb]) # DEBUG
                swathburst.append(data.name[sb])
                # compute the distance with the border of the polygon in km
                CP = AoC.exterior.interpolate(AoC.exterior.project(stationPoint)) # closest point on the AoC border
                convLat = 111.32 # latitude deg to km
                convLon = 40075*np.cos(CP.y*np.pi/180)/360 # longitude deg to km
                dKm = np.sqrt( ( (CP.y-stationPoint.y)*convLat)**2 + ((CP.x-stationPoint.x)*convLon)**2 )
                dist.append(dKm)
                            
                            
    if len(swathburst) < 1:
        raise Exception(f'Reflector {stations[0].id} not imaged in any burst.')

    # group the swathIDs for each station
    maxDistIdx = dist.index(max(dist))
    swathID = swathburst[maxDistIdx].split('_')[1]
    burstID = swathburst[maxDistIdx].split('_')[3]
    
    # DEBUG 
    print(f'swathburst: {swathburst}; dist: {dist}; maxDistIdx: {maxDistIdx}')

    
    slavePath =  '/swath_'+str(swathID)+'/burst_'+burstID+'/'+mode+'.res'
       
        
        
    
    return slavePath,swathID,burstID

# -----------------------------------------               
# Functions for exporting output   
# ----------------------------------------- 

def RCexport(stations,stacks,outDir,plotFlag=1,fullStack=0):
    
    if not os.path.exists(outDir):
        os.makedirs(outDir)
    
    
    for stack in stacks:
        
        acqDates = stack.acqDates

        stackMatrix = []
        RCSanalysis = []
        # AML
        missingStations = []
        # AML END
        
        for station in stations:

            # Find dates where the station was active
            startDate = station.startDate
            endDate = station.endDate

            # get the full dates List from the stack folder (avoid missing dates excluded from the processing)
            dateList = sorted([str(p).split('/')[-1] 
                                   for p in Path(stack.stackDir).glob('[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')])
        

            # if a reduced stack is analyzed, all the dates between start and end Date are marked as 1 (outliers analysis not complete)
            # if the full stack is analyzed, only the dates labeled as good (no outlying value) are marked as 1
            if fullStack:
                stackIdx = station.getStackIdx(stack.id)
                goodIdx = [int(x) for x in station.stacks[stackIdx]["goodIdx"]]
                goodDates = [acqDates[idx] for idx in goodIdx]
                timeRow = [1 if date in goodDates else 0 for date in dateList]
            else:
                timeRow = [1 if ( startDate < date and date < endDate) else 0 for date in dateList]
        
            
            # extract coordinates
            stackIdx = station.getStackIdx(stack.id)
            data = station.stacks[stackIdx]["data"]
            active = np.array(data["status"])
            R = [data["range"][i] for i in range(len(acqDates)) if data["status"][i]]
            Az = [data["azimuth"][i] for i in range(len(acqDates)) if data["status"][i]]
            # AML
            if len(R) == 0 or len(Az) == 0:
                missingStations.append(station.id)
                stRow = [
                    station.id,
                    np.nan,
                    np.nan,
                    np.nan,
                    station.ascending.latitude * (180 / np.pi),
                    station.ascending.longitude * (180 / np.pi),
                    station.ascending.elevation,
                ] + [0 for date in dateList]
                stackMatrix.append(stRow)
                continue
            # AML END
            RCS = station.stacks[stackIdx]["reflRCS"]
            sigRCS = station.stacks[stackIdx]["sigRCS"]
            RCS0 = station.stacks[stackIdx]["RCS0"]-1
                              
            
            # Extract the most common coordinates pair (since it was observed that coregistration errors make the coordinates change in a stack)
            pairs = [(R[i],Az[i]) for i in range(len(R))]
            pCount = Counter(pairs)
            mode = pCount.most_common()
            modeRC = mode[0][0]
                              
            
            
            # plot the predicted RCS versus the measured one with the 3-sigma confidence interval
            cLev = 3
            RCSint = (RCS-cLev*sigRCS,RCS+cLev*sigRCS)
            if (RCS0 <= RCSint[1]):
                if (RCS0 >= RCSint[0]):
                    rFlag = 0
                else:
                    rFlag = +1
            else:
                rFlag = -1

        
            
            RCSanalysis.append([station.id,RCS0,RCS,rFlag,cLev*sigRCS])
                
            # Check if the coordinates variation is bigger than one
            # vFlag = 0
            # azVar = max(Az) - min(Az)
            # rVar = max(R) - min(R)

            # if (azVar > 1) or (rVar > 1):
            #     vFlag = 1


            # write the row for the csv file: ID, RCS check, coordinates, space-time matrix
            stRow = [station.id,rFlag,modeRC[0],modeRC[1],station.ascending.latitude*(180/np.pi),station.ascending.longitude*(180/np.pi),station.ascending.elevation]+timeRow
            #[station.id,rFlag,modeRC[0],modeRC[1]]+timeRow ##AML original 20240610
            
            # fill matrix
            stackMatrix.append(stRow)

            
          
            # plot coordinates timeseries, if required
            if plotFlag > 0:
                fig,axR = plt.subplots(figsize=(20,6))
                plt.rcParams.update({'font.size': 25})
                xlabels = [data["acqDate"][i] for i in range(len(acqDates)) if data["status"][i]]
                axR.plot(range(len(R)),R,color='C0',label='Range',linewidth=0.5,linestyle='-',marker='o')
                axAz = axR.twinx()
                axAz.plot(range(len(Az)),Az,color='C2',label='Azimuth',linestyle='-',marker='*',linewidth=0.5)
                plt.title(f'$\mathbf{{{station.id}}}$ Radar Coordinates - {stack.id}\n$(R,Az)$=({int(modeRC[0])},{int(modeRC[1])})\n\nRCS0={np.round(RCS0,2)} $\hat{{RCS}} \pm 3\sigma$ = ({np.round(RCSint[0],2)},{np.round(RCSint[1],2)}) dBm2\n RCS validation:{rFlag}',fontsize=15)
                
                plt.xlabel('Dates')
                axR.set_xticks(range(len(R)), xlabels, rotation=90)
                axR.grid(axis='x')
                axR.set_ylabel('Range [px]',color='C0')
                axR.set_xlabel('Dates')
                axAz.set_ylabel('Azimuth [px]',color='C2')
                plt.savefig(outDir+station.id+'_'+stack.id+'_RC.png',dpi=100,bbox_inches='tight')
                plt.close()
                
            
            
            
        # export radar coordinates to csv
        csvPath = outDir+stack.id+'_RC.csv'
        bSpaces = ['','','','','','',''] + ['' for i in range(len(dateList))]
        # bSpaces = ['','','',''] + ['' for i in range(len(dateList))]  ## AML original
        with open(csvPath, 'w', newline='') as csvFile:
            csvW = csv.writer(csvFile)
            csvW.writerow(['********']+bSpaces)
            csvW.writerow(['This file contains the Radar Coordinates (RC) of the selected reflectors. RCS test is nominally 0. In case 1 or -1 are displayed, please check manually RCS plots.']+bSpaces)
            csvW.writerow(['stack: '+stack.id,'slc path example: '+stack.files[0]]+bSpaces[0:-1])
            csvW.writerow(['Generated on '+timenow()]+bSpaces)
            csvW.writerow(['********']+bSpaces)
            # csvW.writerow(['ID','Validation','Range','Azimuth']+dateList) ##AML original
            csvW.writerow(['ID','Validation','Range','Azimuth','Lat','Lon','Height']+dateList)
            csvW.writerows(stackMatrix)
            
        print(f'Radar Coordinates exported to: {csvPath}')
        # AML
        if missingStations:
            print(
                f"WARNING: {len(missingStations)} reflector(s) had no valid radar-coordinate "
                f"observations for stack {stack.id}: {', '.join(missingStations)}"
            )
        # AML END
        
        
        # export plot of RCS analysis
        fig,ax = plt.subplots(figsize=(20,4))
        plt.rcParams.update({'font.size': 27})  # Set the font size 
        stIDs = [ID[0] for ID in RCSanalysis]
        RCSmeas = [ID[2] for ID in RCSanalysis]
        RCS0vec = [ID[1] for ID in RCSanalysis]
        RCSnominal = [v[3] for v in RCSanalysis if v[3]==0]
        RCSnonominal = [v[3] for v in RCSanalysis if v[3]!=0]
        x = np.arange(len(stIDs))
        ax.scatter(x, RCSmeas,100,marker='o', color='C7')
        ax.scatter(x, RCS0vec,100,marker='*', color='k',label='RCS0')
        bar_width=0.2
        for i, (stID) in enumerate(stIDs):
               plt.errorbar(x[i], RCSanalysis[i][2],yerr=[[RCSanalysis[i][4]], [RCSanalysis[i][4]]], color='C7', linewidth=2, capsize=4)
        i = 0
        plt.errorbar(x[i], RCSanalysis[i][2], yerr=[[RCSanalysis[i][4]], [RCSanalysis[i][4]]], color='C7',label='$\hat{RCS}\pm 3 \sigma$', linewidth=2, capsize=3)
        bar_width=0.2
        
        ax.set_ylabel('$\mathbf{RCS_{app}}$ [dBm2]')
        ax.set_title(f'RCS_analysis_RC_{stack.id}')
        ax.set_xticks(x)
        ax.set_xticklabels(stIDs)
        ax.set_ylim(RCS0-10,RCS0+10)
        plt.grid(axis='x')
        plt.xticks(rotation=90)
        plt.text(0.01,0.7,f'nominal: {len(RCSnominal)}\nnon-nominal: {len(RCSnonominal)}',color='k',transform=ax.transAxes,
                 bbox=dict(facecolor='white', edgecolor='white', boxstyle='square'))
    
        plt.legend(loc='upper center', bbox_to_anchor=(0.5, 0.3), ncol=3)
        plt.savefig(outDir+'RCSanalysis_'+stack.id+'.png',dpi=100,bbox_inches='tight')
        plt.close()
        

        
    return 

def footPrint(stacks,stations,outDir):
    
    '''
    The function prints the geographic footprint of the radar image, together with the stations' points 
    
    '''
    
    allColors = ['C0','C1','C2','C3','C4','C5','C6','C7']
    
    figA,axA = plt.subplots()
    axA.set_title('All')
    
    for stack,color in zip(stacks,allColors):
        
        stackDir = stack.stackDir
        
        # Load geometry data from swathburst_coverage shapefile
        shpPath = [p for p in Path(stackDir).rglob('../stackburst_coverage.shp')]
        # AML
        if shpPath:
            data = gpd.read_file(shpPath[0]) # Read the Shapefile using geopandas
            geometry = data.geometry
        else:
            aoiShpPath = [p for p in Path(stackDir).rglob('*shape.shp')]
            if not aoiShpPath:
                print(
                    f"WARNING: stackburst_coverage.shp was not found for {stackDir}, "
                    "and no '*shape.shp' AOI fallback was found. Skipping footprint plot."
                )
                continue

            print(
                f"WARNING: stackburst_coverage.shp was not found for {stackDir}. "
                f"Using AOI bounding box from {aoiShpPath[0]} for footprint plotting."
            )
            data = gpd.read_file(aoiShpPath[0])
            geometry = data.geometry.envelope
        # AML END
    

        # Iterate over bursts and stations
        stackName = stackDir.split('/')[-3]
        figS,axS = plt.subplots()
        
        axS.set_title(stackName)

        for sb in range(len(data)):
            # Area of Coverage of current iteration
            AoC = geometry[sb]
            x,y = AoC.exterior.xy
            axS.plot(x, y,color='k',linewidth=.5)
            
            
            if sb==0:
                axA.plot(x, y,color=color,linewidth=.5,label=stackName)
            else:
                axA.plot(x, y,color=color,linewidth=.5)
                
            # plt.plot(x, y, color='blue', alpha=0.7, linewidth=2, solid_capstyle='round', zorder=2)
            
            # for each target
            for loop,station in zip(range(0,len(stations)),stations):
            
                if station.descending:
                    stationPoint = Point(station.descending.longitude*180/np.pi, station.descending.latitude*180/np.pi, station.descending.elevation)
                elif station.ascending:
                    stationPoint = Point(station.ascending.longitude*180/np.pi, station.ascending.latitude*180/np.pi, station.ascending.elevation)
                else:
                    raise Exception('Both ascending and descending are not active...')

                if sb==0:
                    axS.scatter(stationPoint.x,stationPoint.y)
                    axS.text(stationPoint.x,stationPoint.y,station.id,fontsize=8)
                    if color=='C0':
                        axA.scatter(stationPoint.x,stationPoint.y)
                        axA.text(stationPoint.x,stationPoint.y,station.id,fontsize=8)
                        
        
        axS.set_xlabel('Longitude [deg]')
        axS.set_ylabel('Latitude [deg]')
        figS.savefig(outDir+os.sep+stackName+'.png',bbox_inches='tight',dpi=100)
        print(f'image exported to {outDir+os.sep+stackName+".png"}')
        plt.close(figS)
    
    
    axA.set_xlabel('Longitude [deg]')
    axA.set_ylabel('Latitude [deg]')
    axA.legend()
    figA.savefig(outDir+os.sep+'All.png',bbox_inches='tight',dpi=100)
    print(f'image exported to {outDir+os.sep+"All.png"}')
    plt.close()
    
    return
                            

# -----------------------------------------               
# Functions for reading metadata and SLC   
# -----------------------------------------         

def getDownlinkValues(dataPath,folderDate,outPath,centerPoint,swathID):
    
    """
    This function:
    + goes in the dataPath
    + identify the name of the .zip folder by examinating which of .xml files have a polygon containing the point IGRS
    + unzip the identified .zip file, copying the calibration.xml file of the swathID subswath to a temp_calibration.xml file in the outPath
    + open the temp_calibration.xml file and extract the beta0 coefficient TODO: understand why there are so many beta0
    + return beta0
    """

    productsPath = dataPath/folderDate
    xmlPath = [p for p in productsPath.glob('*.xml')]
    if len(xmlPath)<1:
        raise Exception(f'No .xml file specifying product coverage found at {productsPath}')


    if len(xmlPath)>0:
        
        for xmlFile in xmlPath:
            


    
            # Parse the XML file
            try:
                tree = ET.parse(xmlFile)
            except:
                raise Exception(f'The date not working is {folderDate}')
    
            # Get the root element
            root = tree.getroot()

            # Extract the polygon coordinates
            coordinates_element = root.find(".//str[@name='footprint']")
        
            # check if the match is valid
            if coordinates_element is not None:
            
                # VALID --- Extract the coordinates string ------------
                if coordinates_element.text[0] == 'P':
                    # POLYGON
                    coordinates = coordinates_element.text[10:-2].split(',')
                else:
                    # MULTIPOLYGON
                    coordinates = coordinates_element.text[16:-3].split(', ')
                # ------------------------------------------------------
                
            else:
                # NOT VALID ------ raise exception
                raise Exception('[footprint] coordinates not found in file: '+xmlFile.name)

        

            # Extract x and y coordinates
            xy_coordinates = [coord.split(' ') for coord in coordinates]
            x_coordinates = [float(xy[0]) for xy in xy_coordinates]
            y_coordinates = [float(xy[1]) for xy in xy_coordinates]

            # Create Shapely polygon object
            AoC = Polygon(zip(x_coordinates, y_coordinates))

            # if polygon contains the AoI, select .zip file
            if AoC.contains(centerPoint):
                zipName = xmlFile.name[0:-4]+'.zip'
                zipFile = productsPath/zipName
            
                    # print(folderDate + ': Corresponding .zip found --> ' + zipFile)
                break
                    

            
    # extract the .xml file and copy it to the output folder
    outFile = outPath+'temp_calibration.xml'
    calPath = zipName[0:-4]+'.SAFE/annotation/calibration/calibration*iw'+str(swathID)+'*vv*.xml'

    


    command = f"unzip -p {zipFile} {calPath} > {outFile}" 
    completedProcess = subprocess.run(command, shell=True)
    returnCode = completedProcess.returncode
    
    if returnCode != 0:
        raise Exception(f'calibration.xml extraction NOT succesful. Return code: {returnCode}.\ncommand executed: {command}')
        
    # read the betaNought
    
    # Parse the XML file
    tree = ET.parse(outFile)
    
    # Get the root element
    root = tree.getroot()
        
    beta = root.find('.//betaNought')

    if beta is not None:
        # Extract the pixel values
        betaValues = beta.text.strip().split(' ')
        betaValues = [float(value) for value in betaValues]
        beta0 = np.unique(betaValues)

        if len(beta0) != 1:
            print('WARNING: betaNought not unique')
    else:
        raise Exception("betaNought element not found in the XML.")
        
    # Check if the file exists before deleting
    if os.path.exists(outFile):
        # Delete the file
        os.remove(outFile)
    else:
        print("temp_calibration.xml not removed because not found.")
    
    beta0 = beta0[0]

    # extract annotation informations
    outFile = outPath+'temp_annotation.xml'
    annPath = zipName[0:-4]+'.SAFE/annotation/s1*-iw'+str(swathID)+'*vv*.xml'
   

    
    command = f"unzip -p {zipFile} {annPath} > {outFile}"
    completedProcess = subprocess.run(command, shell=True)
    returnCode = completedProcess.returncode
    
    if returnCode != 0:
        raise Exception(f'annotation.xml extraction NOT succesful. Return code: {returnCode}.\ncommand executed: {command}')
        
    # Parse the XML file
    tree = ET.parse(outFile)
    
    # Get the root element
    root = tree.getroot()
    
    # rank
    rank = root.find('.//rank')
    
    if rank is not None:
        rankValue = int(rank.text.strip())

    else:
        raise Exception("rank element not found in the XML.")
        
    # chirpRate
    txPulseRampRate = root.find('.//txPulseRampRate')
    
    if rank is not None:
        chirpRate = float(txPulseRampRate.text.strip())

    else:
        raise Exception("rank element not found in the XML.")
    

 
    return beta0,rankValue,chirpRate

def getOrbit(acqDate,satID,PRF,nAzimuth,orbType = 'precise'):
    
    '''
    Function to get observation vectors from AUX_*OE products
    
    orbType is by default 'precise', but could be 'restituted','medium' (currently undergoing testing)
    
    '''
    # absolute path of the sentinel1 orbits folder
    orbitPath = '/project/caroline/Data/orbits/sentinel1/'+orbType+'/'
    if orbType == 'medium':
        orbitPath = '/project/caroline/Share/users/caroline-pbazzocchi/medium/'
    
    firstUTC = acqDate - timedelta(seconds=10*12)
    lastUTC = acqDate + timedelta(seconds=nAzimuth/PRF+10*12)
    nPoints = int((lastUTC - firstUTC).seconds/10)

    
    startTime = firstUTC.strftime('%Y-%m-%dT%H:%M:%S.%f')
    fileBounds = [firstUTC,lastUTC]
    LastTime = lastUTC.strftime('%Y-%m-%dT%H:%M:%S.%f')
    
    # initialize orbit array
    orbit = np.zeros((nPoints,7))
    idx = 0

  


    fileList = [f for f in Path(orbitPath).glob(satID+'*.EOF')]

    for fileName in fileList: 
        
        fileName = str(fileName)
        f = fileName.split('_')
        
        startFile = datetime.strptime(f[-2][1:],'%Y%m%dT%H%M%S')
        endFile = datetime.strptime(f[-1][0:-4],'%Y%m%dT%H%M%S')
        

        if (startFile <= fileBounds[0]) and (endFile >= fileBounds[1]):
            # start extraction
            obsStart = int((fileBounds[0]-startFile).seconds/10)
            try:
                tree = ET.parse(fileName)
            except:
                raise Exception(f'Parse failed for date: {acqDate}, orbitFile: {fileName}')
            
            root = tree.getroot()
            osv_list = root.findall(".//OSV")
            osvRed = osv_list[obsStart-1:obsStart+nPoints-1]
            
            

                      
            for osv in osvRed:
                UTC = osv.find('./UTC').text
                timestamp = datetime.strptime(UTC, 'UTC=%Y-%m-%dT%H:%M:%S.%f')
                SoD = (timestamp - timestamp.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
                orbit[idx,0] = SoD
                orbit[idx,1] = float(osv.find(".//X").text)
                orbit[idx,2] = float(osv.find(".//Y").text)
                orbit[idx,3] = float(osv.find(".//Z").text)
                orbit[idx,4] = float(osv.find(".//VX").text)
                orbit[idx,5] = float(osv.find(".//VY").text)
                orbit[idx,6] = float(osv.find(".//VZ").text)

                idx+=1
            
            break
      
    if idx!=0:
        return orbit
    
    print('Checking in missing folder...')
    fileList = [f for f in Path('/project/caroline/Share/users/caroline-pbazzocchi/'+orbType+'/').glob(satID+'*.EOF')]
        
        
    for fileName in fileList: 
        
        fileName = str(fileName)
        f = fileName.split('_')
        
        startFile = datetime.strptime(f[-2][1:],'%Y%m%dT%H%M%S')
        endFile = datetime.strptime(f[-1][0:-4],'%Y%m%dT%H%M%S')
        

        if (startFile <= fileBounds[0]) and (endFile >= fileBounds[1]):
            # start extraction
            obsStart = int((fileBounds[0]-startFile).seconds/10)
            try:
                tree = ET.parse(fileName)
            except:
                raise Exception(f'Parse failed for date: {acqDate}, orbitFile: {fileName}')
            
            root = tree.getroot()
            osv_list = root.findall(".//OSV")
            osvRed = osv_list[obsStart-1:obsStart+nPoints-1]
            
            

                      
            for osv in osvRed:
                UTC = osv.find('./UTC').text
                timestamp = datetime.strptime(UTC, 'UTC=%Y-%m-%dT%H:%M:%S.%f')
                SoD = (timestamp - timestamp.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
                orbit[idx,0] = SoD
                orbit[idx,1] = float(osv.find(".//X").text)
                orbit[idx,2] = float(osv.find(".//Y").text)
                orbit[idx,3] = float(osv.find(".//Z").text)
                orbit[idx,4] = float(osv.find(".//VX").text)
                orbit[idx,5] = float(osv.find(".//VY").text)
                orbit[idx,6] = float(osv.find(".//VZ").text)

                idx+=1
            
            break
     
    if idx==0:
        raise Exception(f'Orbit data not found for date: {acqDate}')
            
    return orbit

def datetimeToMJD(dt):

    # Reference datetime for MJD calculation (November 17, 1858)

    referenceDatetime = datetime(1858, 11, 17)
 
    # Calculate the time difference in days

    timeDifference = dt - referenceDatetime
 
    # Calculate the total number of days (including fractions)

    totalDays = timeDifference.days + timeDifference.seconds / (24 * 3600)
 
 
    # Calculate the Modified Julian Date (MJD)

    MJD = totalDays #- 2400000.5
 
    return MJD
    
def readMetadata(resFile,dataPath,outPath,mode='raw',**kwargs):
    
    # type of image: stitched: TRUE / burst: FALSE
    imgType = str(resFile).split(os.sep)[-2].isdigit()

    # check cropFlag
    if mode == 'coreg' and 'crop' in kwargs:
        cropFlag = kwargs['crop']
    else:
        cropFlag = 0
    
    # Open the file
    with open(resFile, 'r') as file:
        content = file.read()
        
    # +++   - Satellite ID
    pattern = r'Product type specifier:\s+(.*?(?=\n))'
    match = re.search(pattern,content)
    satID = match.group(1).upper()
    
    # ++++1 - Geometry [DESCENDING or ASCENDING]
    pattern = r'PASS:\s+(.*?(?=\n))'
    match = re.search(pattern,content)
    geometry = match.group(1).upper()
    
    # ++++ 2 - Acquisition Date [dictionary with __datetime__ and str, in the format 'yyyy-mm-dd hh:mm:ss']
    # pattern = r'First_pixel_azimuth_time \(UTC\):\s+(\d+-\w+-\d+\s+)(\d+:\d+:\d+.\d+)' # DEBUG removed the decimal, not needed
    pattern = r'First_pixel_azimuth_time \(UTC\):\s+(\d+-\w+-\d+\s+)(\d+:\d+:\d+)'
    match = re.search(pattern,content)
    
    # --- extract the datetime string
    datetime_toconvert = match.group(1)+match.group(2)
    # Parse the original datetime string
    # acqDate = datetime.datetime.strptime(datetime_toconvert, "%Y-%b-%d %H:%M:%S.%f") # DEBUG removed .%f, not needed
    acqDate = datetime.strptime(datetime_toconvert, "%Y-%b-%d %H:%M:%S")
    folderDate = acqDate.strftime("%Y%m%d")

    

    
    # ++++ 3 - azimuth0time
    
    # convert from time format to seconds of the day
    a0t_string = match.group(2)
    pattern = r'(\d+):(\d+):(\d+.\d+)'
    match = re.search(pattern,content)
    azimuth0time = int(match.group(1))*3600 + int(match.group(2))*60 + float(match.group(3))
    
    # ++++ 4 - range0time
    pattern = r'Range_time_to_first_pixel \(2way\) \(ms\):'+sc_n_pattern
    match = re.search(pattern,content)
    range0time = float(match.group(1))*1e-3
    
    # ++++ 5 - PRF
    pattern = r'Pulse_Repetition_Frequency \(computed, Hz\):'+sc_n_pattern
    match = re.search(pattern,content)
    PRF = float(match.group(1))
    
    # ++++ 6 - RSR
    pattern = r'Range_sampling_rate \(computed, MHz\):'+sc_n_pattern
    match = re.search(pattern,content)
    RSR = float(match.group(1))*1e6*2
    
    # ++++ 7 - wavelenght
    pattern = r'Radar_wavelength \(m\):'+sc_n_pattern
    match = re.search(pattern,content)
    wavelength = float(match.group(1))
    
    # ++++ 8 - orbitFit
    
    # Define the regular expression pattern to match the table rows
    pattern = r"(\d+)\s+([-+]?\d+\.\d+(?:\.\d+)?)\s+([-+]?\d+\.\d+(?:\.\d+)?)\s+([-+]?\d+\.\d+(?:\.\d+)?)"

    # extract the table rows
    table_rows = re.findall(pattern, content)
    
    orbit = np.ones((len(table_rows),4))
    
    for i in range(len(table_rows)):
        for j in range(4):
            orbit[i][j] = float(table_rows[i][j])
            
    # Generate the orbFit dictionary
    orbFit = geoUtils.orbitFit(orbit, verbose = 0, plotFlag = 0)
        
    # ++++ 9 - rangeSpacing
    pattern = r'rangePixelSpacing:'+sc_n_pattern
    match = re.search(pattern,content)
    rangeSpacing = float(match.group(1))
    
    # ++++ 10 - azimuthSpacing
    pattern = r'azimuthPixelSpacing:'+sc_n_pattern
    match = re.search(pattern,content)
    azimuthSpacing = float(match.group(1))
    
    # ++++ 11 - centerLon
    pattern = r'Scene_centre_longitude:'+sc_n_pattern
    match = re.search(pattern,content)
    centerLon = float(match.group(1))
    
    # ++++ 12 - centerLat
    pattern = r'Scene_centre_latitude:'+sc_n_pattern
    match = re.search(pattern,content)
    centerLat = float(match.group(1))
    
    # ++++ 13 - centerH
    pattern = r'Scene_center_heading:'+sc_n_pattern
    match = re.search(pattern,content)
    centerH = float(match.group(1))
    
    
    # ++++ 14 - nAzimuth
    pattern = r'Number_of_lines_original:'+sc_n_pattern
    match = re.search(pattern,content)
    nAzimuth = int(match.group(1))
    
    # ++++ 15 - nRange
    pattern = r'Number_of_pixels_original:'+sc_n_pattern
    match = re.search(pattern,content)
    nRange = int(match.group(1))
    
    # ++++ 16 - swath
    pattern = r'SWATH:\s+IW(\d+)'
    match = re.search(pattern,content)
    swath = int(match.group(1))
    
    # ++++ 17 - centerAzimuth
    centerAzimuth = np.round(nAzimuth/2)
    
    # ++++ 18 - beta0, rank, chirprate

    # extract from original product
    # ----------------------------------------------
    # centerPoint = Point(centerLon,centerLat)
    # try:
    #     beta0,rank,chirpRate = getDownlinkValues(dataPath,folderDate,outPath,centerPoint,swath)
    # except Exception as e:
    #     print(f'WARNING: date {acqDate} raised exception.\nbeta0, rank and chirpRate values replaced with default. To learn more, check Exception.txt')
    #     with open(outPath+'Exception.txt','a') as file:
    #         file.write(f'\nException for {acqDate}: {e}\n')
        
    #     # replace values with common values
    #     beta0 = 237 
    #     if swath == 1:
    #         rank = 9
    #         chirpRate = 1078230321255.894
    #     elif swath == 2:
    #         rank = 8
    #         chirpRate = 779281727512.0481
    #     elif swath == 3:
    #         rank = 10
    #         chirpRate = 801450949070.5804
    # -----------------------------------------------

    # ++++ 18 - beta0, rank, chirprate
    beta0 = 237 
    if swath == 1:
        rank = 9
        chirpRate = 1078230321255.894
    elif swath == 2:
        rank = 8
        chirpRate = 779281727512.0481
    elif swath == 3:
        rank = 10
        chirpRate = 801450949070.5804

    
   
    # resolutions [from s1 annual performance reports]
    azResolutions = np.array([21.76,21.89,21.71])
    rResolutions = np.array([2.63,3.09,3.51])
    azimuthResolution = azResolutions[swath-1]
    
    # ++++ 20 - rangeResolution
    pattern = r'Total_range_band_width \(MHz\):'+sc_n_pattern
    match = re.search(pattern,content)
    rangeResolution = speedOfLight/(2*float(match.group(1))*1e6)
    
    # ++++ 21 - nBursts
    if not imgType:
        nBursts = 1
    
        # ++++ 22 - burstInfo
        pattern = r'burst_(\d+)'
        match = re.search(pattern,str(resFile))
        burstN = int(match.group(1))
    else:
        burstN = None
        nBurst = None

    # ++++ 23 - steeringRate
    pattern = r'Azimuth_steering_rate \(deg/s\):'+sc_n_pattern
    match = re.search(pattern,content)
    steeringRate = float(match.group(1))*np.pi/180

        
    # ++++ 24 - azFmRateArray
    
    # FM_reference_azimuth_time
    pattern = r'FM_reference_azimuth_time:\s+(\d+-\w+-\d+\s+)(\d+:\d+:\d+.\d+)'
    match = re.search(pattern,content)
    
    # extract the datetime string
    datetime_toconvert = match.group(1)+match.group(2)
    # Parse the original datetime string
    dt = datetime.strptime(datetime_toconvert, "%Y-%b-%d %H:%M:%S.%f")
    t_epoch = datetimeToMJD(dt)*86400

    
    # FM_reference_range_time
    pattern = r'FM_reference_range_time:'+sc_n_pattern
    match = re.search(pattern,content)
    t0 = float(match.group(1)) 
    
    # FM_polynomial_constant_coeff
    pattern = r'FM_polynomial_constant_coeff \(Hz, early edge\):'+sc_n_pattern
    match = re.search(pattern,content)
    c0 = float(match.group(1))
    
    # FM_polynomial_linear_coeff
    pattern = r'FM_polynomial_linear_coeff \(Hz/s, early edge\):'+sc_n_pattern
    match = re.search(pattern,content)
    c1 = float(match.group(1))
    
    # FM_polynomial_quadratic_coeff
    pattern = r'FM_polynomial_quadratic_coeff \(Hz/s/s, early edge\):'+sc_n_pattern
    match = re.search(pattern,content)
    c2 = float(match.group(1))
    
    # Assembly
    azFmRateArray = [{
        "t": t_epoch,
        "t0": t0,
        "c0": c0,
        "c1": c1,
        "c2": c2
    }]

    # ++++ 25 - dcPolyArray
    
    # DC_reference_azimuth_time
    pattern = r'DC_reference_azimuth_time:\s+(\d+-\w+-\d+\s+)(\d+:\d+:\d+.\d+)'
    pattern = r'FM_reference_azimuth_time:\s+(\d+-\w+-\d+\s+)(\d+:\d+:\d+.\d+)'
    match = re.search(pattern,content)
    
    # extract the datetime string
    datetime_toconvert = match.group(1)+match.group(2)
    # --- Parse the original datetime string
    dt = datetime.strptime(datetime_toconvert, "%Y-%b-%d %H:%M:%S.%f")
    t_epoch = datetimeToMJD(dt)*86400
    
    # DC_reference_range_time
    pattern = r'DC_reference_range_time:'+sc_n_pattern
    match = re.search(pattern,content)
    t0 = float(match.group(1)) # <--------- this is probably an epoch?
    
    # Xtrack_f_DC_constant (Hz, early edge):
    pattern = r'Xtrack_f_DC_constant \(Hz, early edge\):'+sc_n_pattern
    match = re.search(pattern,content)
    c0 = float(match.group(1))
    
    # Xtrack_f_DC_linear (Hz/s, early edge):
    pattern = r'Xtrack_f_DC_linear \(Hz/s, early edge\):'+sc_n_pattern
    match = re.search(pattern,content)
    c1 = float(match.group(1))
    
    # FM_polynomial_quadratic_coeff
    pattern = r'Xtrack_f_DC_quadratic \(Hz/s/s, early edge\):'+sc_n_pattern
    match = re.search(pattern,content)
    c2 = float(match.group(1))
    
    # Assembly
    dcPolyArray = [{
        "t": t_epoch,
        "t0": t0,
        "c0": c0,
        "c1": c1,
        "c2": c2
    }]

    

    # ++++ 26 - PRI
    pattern = r'Pulse_Repetition_Frequency_raw_data\(TOPSAR\):'+sc_n_pattern
    match = re.search(pattern,content)
    PRI = 1/float(match.group(1))
    
    # ++++ 27 - rank
    # See Beta0 section

    # ++++ 28 - chirpRate
    
    
    # ++++ 29 - nAzimuth
    if cropFlag:
        cropFile = '/'.join(str(resFile).split('/')[0:-2])+'/nlines_crp.txt'
        with open(cropFile,'r') as file:
            content = file.readlines()
            nLines,first_line,last_line = int(content[0].strip()),int(content[1].strip()),int(content[2].strip())
        
    else:        
        # Extract first
        pattern = r'First_line \(w.r.t. original_image\):'+sc_n_pattern
        match = re.search(pattern,content)
        first_line = int(match.group(1))
        # Extract last
        pattern = r'Last_line \(w.r.t. original_image\):'+sc_n_pattern
        match = re.search(pattern,content)
        last_line = int(match.group(1))
        # difference
        nLines = last_line-first_line+1
    

    # ++++ 30 - nRange
    if cropFlag:
        cropFile = '/'.join(str(resFile).split('/')[0:-2])+'/npixels_crp.txt'
        with open(cropFile,'r') as file:
            content = file.readlines()
            nPixels,first_pixel,last_pixel = int(content[0].strip()),int(content[1].strip()),int(content[2].strip())
    else:
        # Extract first
        pattern = r'First_pixel \(w.r.t. original_image\):'+sc_n_pattern
        match = re.search(pattern,content)
        first_pixel = int(match.group(1))
        # Extract last
        pattern = r'Last_pixel \(w.r.t. original_image\):'+sc_n_pattern
        match = re.search(pattern,content)
        last_pixel = int(match.group(1))
        # difference
        nPixels = last_pixel-first_pixel+1
    
    
        
        
    
    # ----------------------------------------
    
    # orbit from external source
    # orbit = getOrbit(acqDate,satID,PRF,nAzimuth,'medium')
    # orbFit = geoUtils.orbitFit(orbit, verbose = 0, plotFlag = 0,der=False)
    
    # ----------------------------------------
    
    # Fill the dictionary
    datewise_metadata = {
        "orbit": geometry,
        "acqDate": acqDate,
        "azimuth0time": azimuth0time,
        "range0time": range0time/2,
        "PRF": PRF,
        "RSR": RSR,
        "wavelength": wavelength,
        "orbitFit": orbFit,
        "rangeSpacing": rangeSpacing,
        "azimuthSpacing": azimuthSpacing,
        "centerLon": centerLon,
        "centerLat": centerLat,
        "centerH": centerH,
        "nAzimuth": nAzimuth,
        "nRange": nRange,
        "1stAzimuth": first_line,
        "1stRange": first_pixel,
        "swath": swath,
        "centerAzimuth": centerAzimuth,
        "beta0": beta0, 
        "azimuthResolution": azimuthResolution,
        "rangeResolution": rangeResolution,
        "nBursts": 1,
        "burstInfo":burstN, 
        "steeringRate": steeringRate, 
        "azFmRateArray":azFmRateArray,
        "dcPolyArray": dcPolyArray, 
        "PRI": PRI,
        "rank": rank,
        "chirpRate": chirpRate, 
        "nLines" : nLines,
        "nPixels": nPixels
        # -------------------------------------------------------------------
    }
    
    return datewise_metadata

def readSLC(file,metadata,boundingBox,method = 'raw'):

    
    
    if method=='coreg':
        shape=(metadata["nLines"], metadata["nPixels"])
        dtype = np.dtype(np.complex64)
        filePath = [Path(f) for f in file]
        SLC = sarxarray.from_binary(filePath, shape, dtype=dtype)
        
        
    elif method == 'select':
        minAz = int(boundingBox[0][0])
        maxAz = int(boundingBox[0][1])
        minR = int(boundingBox[1][0])
        maxR = int(boundingBox[1][1])
        
        return file.isel(azimuth=range(minAz,maxAz),range=range(minR,maxR),time=metadata)
    
    elif method == 'crop':
        minAz = int(boundingBox[0][0])
        maxAz = int(boundingBox[0][1])
        minR = int(boundingBox[1][0]) 
        maxR = int(boundingBox[1][1]) 
        slc = file.isel(azimuth=range(minAz,maxAz),range=range(minR,maxR))

        return slc.values

    elif method=='coregSingle':
        shape=(metadata["nLines"], metadata["nPixels"])    
        dtype = np.dtype(np.complex64)
        
        filePath = [Path(file)]
        fullSLC = sarxarray.from_binary(filePath, shape, dtype=dtype)
        SLC = fullSLC.isel(time=0)
    
    elif method=='coregCrop':
        shape=(metadata["nLines"], metadata["nPixels"])    
        dtype = np.dtype(np.complex64)
        
        filePath = [Path(file)]
        fullSLC = sarxarray.from_binary(filePath, shape, dtype=dtype,chunks=(200,200))
        SLC = fullSLC.isel(time=0)
        
    elif method=='raw':
        shape=(metadata["nLines"], metadata["nPixels"])
        minAz = int(boundingBox[0][0])# - metadata["1stAzimuth"]
        maxAz = int(boundingBox[0][1])# - metadata["1stAzimuth"]
        minR = int(boundingBox[1][0]) # - metadata["1stRange"]
        maxR = int(boundingBox[1][1]) # - metadata["1stRange"]
        sizeAz = maxAz-minAz+1
        sizeR = maxR-minR+1
    
        dtype = np.dtype([('re', np.int16), ('im', np.int16)])
        
        filePath = [Path(file)]
        fullSLC = sarxarray.from_binary(filePath, shape, dtype=dtype,chunks=(200,200))
    
        SLC = fullSLC.isel(azimuth=range(minAz,maxAz),range=range(minR,maxR),time=0)
    
    

    
    return SLC.complex
        

# -----------------------------------------  
    
    
    
    


