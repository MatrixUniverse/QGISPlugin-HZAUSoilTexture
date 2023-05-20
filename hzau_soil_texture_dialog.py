# -*- coding: utf-8 -*-
"""
/***************************************************************************
 HZAUSoilTextureDialog
                                 A QGIS plugin
 使用砂粒和黏粒栅格数据生成土壤质地图
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2023-03-14
        git sha              : $Format:%H$
        copyright            : (C) 2023 by 邓阳
        email                : dengyang.chn@foxmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from __future__ import absolute_import

from builtins import zip
from builtins import str
from builtins import range


from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt import QtGui
from qgis.core import *
from qgis.gui import *

import os, sys, time
from osgeo import gdal
from osgeo import ogr
from osgeo import osr
from osgeo.gdalconst import *

import numpy as np
from matplotlib.path import Path
import fnmatch
import webbrowser

# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'hzau_soil_texture_dialog_base.ui'))


class HZAUSoilTextureDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, iface):
        """构造函数 Constructor."""
        QtWidgets.QDialog.__init__(self)
        self.iface = iface
        # Set up the user interface from Designer through FORM_CLASS.
        # After self.setupUi() you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)

        self.btnOutput.clicked.connect(self.outFile)
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setText("确认")
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Close).setText("关闭")
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Help).setText("源码")
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.buttonBox.helpRequested.connect(self.open_source)

        mapCanvas = self.iface.mapCanvas()
        # init dictionaries of items:
        self.cmbSand.addItem("")
        self.cmbClay.addItem("")
        self.rastItems = {}
        for i in range(mapCanvas.layerCount()):
            layer = mapCanvas.layer(i)
            if layer.type() == layer.RasterLayer:
                # read  layers
                provider = layer.dataProvider()
                self.cmbSand.addItem(layer.source())
                self.cmbClay.addItem(layer.source())

        currentDIR = str(os.path.abspath(os.path.dirname(__file__)))
        listDat = [s for s in os.listdir(currentDIR) if fnmatch.fnmatch(s, '*.dat')]
        self.cmbSchema.addItems(listDat)
        print(currentDIR, listDat)
        self.textEdit.clear()

    def outFile(self):
        """为土壤质地输出文件显示文件对话框"""
        self.lineOutput.clear()
        outName = QFileDialog.getSaveFileName(self, "Texture output file", ".", "GeoTiff (*.tif)")
        print(outName[0])
        # if not outName.isEmpty():
        self.lineOutput.clear()
        self.lineOutput.insert(outName[0])
        return outName

    def readSchema(self, schema):
        """读取土壤质地分类规则文件"""
        # ---------------------------------------------------------
        #   x=sand, y=clay bi-axial texture triangle
        # ---------------------------------------------------------
        try:
            f1 = open(schema, "r")
            numpoly = f1.readline()
            numpoly = int(numpoly)
            RuleList = [numpoly]
            for i in range(numpoly):
                texture = f1.readline().split()
                num_vert = f1.readline().split()
                sand_vert = f1.readline().split()
                clay_vert = f1.readline().split()
                TextureRule = {'Texture': texture, 'Num_vert': num_vert, 'Sand_vert': sand_vert, 'Clay_vert': clay_vert,}
                RuleList.insert(i, TextureRule)  # 'list of roule dictionary
            legend = [line for line in f1.read().split('\n')]
            f1.close()

            for i in range(numpoly):
                RuleList[i]['Texture'][0] = int(RuleList[i]['Texture'][0])
                RuleList[i]['Num_vert'][0] = int(RuleList[i]['Num_vert'][0])
                for j in range(RuleList[i]['Num_vert'][0]):
                    RuleList[i]['Clay_vert'][j] = float(RuleList[i]['Clay_vert'][j])
                    RuleList[i]['Sand_vert'][j] = float(RuleList[i]['Sand_vert'][j])
            self.textEdit.clear()
            for l in legend:
                self.textEdit.append(l)
                print(l)
            return RuleList, numpoly, legend

        except:
            QMessageBox.warning(None, "警告", "文件 %s 不存在或无法打开！" % schema)
            return

    def ProcessRaster(self, sand, clay):
        """注册所有的GDAL驱动程序"""
        gdal.AllRegister()
        # open the image
        sand = str(sand)
        clay = str(clay)

        imgSand = gdal.Open(sand, GA_ReadOnly)
        if imgSand is None:
            QMessageBox.warning(None, "警告", "不存在或无法打开砂粒图 %s " % sand)

        imgClay = gdal.Open(clay, GA_ReadOnly)
        if imgClay is None:
            QMessageBox.warning(None, "警告", "不存在或无法打开粘粒图 %s " % clay)

        # get image size
        rows = imgClay.RasterYSize
        cols = imgClay.RasterXSize
        bands = imgClay.RasterCount
        if bands > 1:
            QMessageBox.warning(None, "警告", "栅格影像 %s 有 %d 波段,本程序只能处理单波段影像!" % (clay, bands))

        # get georeference info
        transform = imgClay.GetGeoTransform()
        xOrigin = transform[0]
        yOrigin = transform[3]
        pixelWidth = transform[1]
        pixelHeight = transform[5]
        dataClay = imgClay.ReadAsArray()
        dataSand = imgSand.ReadAsArray()
        return dataClay, dataSand, rows, cols, transform

    def InsidePolygon(self, RuleList, numpoly, xS, yC):
        """确定点是位于质地三角形内还是外"""
        NODATA = -9999
        for p in range(numpoly):
            polygon = []
            isInside = False
            num_vert = int(RuleList[p]['Num_vert'][0])
            texture = RuleList[p]['Texture'][0]  # numeric code define texture
            sand = RuleList[p]['Sand_vert']  # coord. list of texturale polugons
            clay = RuleList[p]['Clay_vert']  #
            if (xS < 0 or yC < 0):
                return NODATA
            else:
                polygon = np.asarray([[sand[i], clay[i]] for i in range(len(clay))])
                path = Path(polygon)
                isInside = path.contains_point([xS, yC])
                if isInside == True:
                    return texture

    def writeTextureGeoTiff(self, arrayData, transform, rows, cols, outFile):
        """将给定的数组数据写入具有给定范围的文件“outfile”"""
        try:
            format = "GTiff"
            driver = gdal.GetDriverByName(format)
            NOVALUE = -9999
            metadata = driver.GetMetadata()
            # if metadata.has_key(gdal.DCAP_CREATE) and metadata[gdal.DCAP_CREATE] == 'YES':
            #     pass
            # else:
            #     QMessageBox.information(None,"info","Driver %s does not support Create() method." % format)
            #     return False
            outDataset = driver.Create(str(outFile), cols, rows, 1, gdal.GDT_Byte)
            outTexture = outDataset.GetRasterBand(1)
            outTexture.WriteArray(arrayData)
            outTexture.SetNoDataValue(NOVALUE)
            outDataset.SetGeoTransform(transform)
            print(transform)
            return True
        except:
            QMessageBox.warning(None, "警告", "程序无法将数据写入质地文件 %s " % outFile)
            return 1

    def loadTextureRaster(self, outFile):
        """在TOC中加载质地栅格图"""
        fileInfo = QFileInfo(outFile)
        baseName = fileInfo.baseName()
        rlayer = QgsRasterLayer(outFile, baseName)
        if not rlayer.isValid():
            self.textEdit.append("土壤质地栅格图层加载失败!")
        # rlayer.setDrawingStyle(QgsRasterLayer.SingleBandPseudoColor)
        # rlayer.setColorShadingAlgorithm(QgsRasterLayer.FreakOutShader)
        QgsProject.instance().addMapLayer(rlayer)
        return rlayer

    def rast2vect(self, rasterTexture, legend):
        """将栅格图转换为矢量图"""
        gdal.AllRegister()
        options = []
        # open the image
        rasterTexture = str(rasterTexture)
        srcRaster = gdal.Open(rasterTexture, GA_ReadOnly)
        srcband = srcRaster.GetRasterBand(1)
        spatialReference = osr.SpatialReference()
        spatialReference.ImportFromWkt(srcRaster.GetProjectionRef())
        # 	Create output file.
        pathSource = os.path.dirname(rasterTexture)
        fileName = os.path.splitext(os.path.basename(rasterTexture))[0]
        driver = ogr.GetDriverByName('ESRI Shapefile')
        dstPath = os.path.join(pathSource, fileName + ".shp")
        dstFile = driver.CreateDataSource(dstPath)
        if os.path.exists(dstPath) == False:
            # Find or create destination layer.
            dstLayer = dstFile.CreateLayer("layer", spatialReference)
            # Create texture int code field from raster value
            fieldDef = ogr.FieldDefn("code", ogr.OFTInteger)
            dstLayer.CreateField(fieldDef)
            dst_field = 0
            # Polygonize
            prog_func = gdal.TermProgress
            gdal.Polygonize(srcband, None, dstLayer, dst_field, options, callback=None)
            # Create texture label field
            fieldLabel = ogr.FieldDefn('label_txt', ogr.OFTString)
            fieldLabel.SetWidth(50)
            dstLayer.CreateField(fieldLabel)
            # fieldLabel = 1
            codeList = [line.split("=") for line in legend[1:-1]]
            codeDict = {int(v[0]): v[1] for (v) in codeList}
            for i in range(dstLayer.GetFeatureCount()):
                feature = dstLayer.GetFeature(i)
                code = feature.GetField("code")
                iIndex = feature.GetFieldIndex("label_txt")
                feature.SetField(iIndex, str(codeDict[code]))
                dstLayer.SetFeature(feature)
                feature.Destroy()
            dstFile.Destroy()
            return dstPath
        else:
            self.textEdit.append("""<b>此次处理只有土壤质地栅格文件能完成创建，
                因为存在一个有相同输出名称的土壤质地矢量文件，
                所以本矢量文件将无法被创建！<\b>""")
            return 'None'

    def loadTextureVector(self, vectorTexture):
        """在画布中加载质地矢量图"""
        if os.path.exists(vectorTexture):
            layer = QgsVectorLayer(vectorTexture, str(os.path.basename(vectorTexture).split('.')[0]), "ogr")
            QgsProject.instance().addMapLayer(layer)
        else:
            return 0

    def open_source(self):
        """Github源码网址"""
        """本插件主要代码来源于Gianluca Massei（http://maplab.alwaysdata.net/）"""
        webbrowser.open("https://github.com/MatrixUniverse/QGISPlugin-HZAUSoilTexture")

    def plotFile(self, dataClay, dataSand, outFile):
        """"生成质地三角形中砂粒sand、粉粒silt、粘粒clay的坐标csv文件"""
        outDIR = str(os.path.abspath(os.path.dirname(outFile)))
        ternaryPlot = os.path.join(outDIR, str(os.path.basename(outFile).split('.')[0]) + '_ternaryPlot.csv')
        pf = open(ternaryPlot, 'w')
        pf.write('CLAY,SAND,SILT\n')
        for crow, srow in zip(dataClay, dataSand):
            for c, s in zip(crow, srow):
                if c >= 0 and s >= 0:
                    values = '%s,%s,%s\n' % (c, s, (100 - c - s))
                    pf.write(values)
        pf.close()

    def accept(self):
        """当‘确认’按钮被单击后执行"""

        clay = self.cmbClay.currentText()
        sand = self.cmbSand.currentText()
        currentDIR = str(os.path.abspath(os.path.dirname(__file__)))
        schema = self.cmbSchema.currentText()
        schema = os.path.join(currentDIR, str(schema))
        outFile = self.lineOutput.text()
        self.textEdit.append("开始处理...")

        RuleList, numpoly, legend = self.readSchema(schema)
        dataClay, dataSand, rows, cols, transform = self.ProcessRaster(sand, clay)
        self.progressBar.setRange(0, rows)

        TextureList = []
        row = []
        self.textEdit.append("行：%d, 列：%d" % (rows, cols))

        for i in range(rows):
            self.progressBar.setValue(i+1)
            row = [self.InsidePolygon(RuleList, numpoly, dS, dC) for (dS, dC) in zip(dataSand[i], dataClay[i])]
            TextureList.append(row)

        TextureList = np.asarray(TextureList)
        self.writeTextureGeoTiff(TextureList, transform, rows, cols, outFile)
        vectorTexture = self.rast2vect(outFile, legend)
        print(vectorTexture)
        self.plotFile(dataClay, dataSand, outFile)
        self.textEdit.append("结束！")
        if self.checkBox.isChecked() == True:
            self.loadTextureRaster(outFile)
            self.loadTextureVector(vectorTexture)
