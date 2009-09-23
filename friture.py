#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2009 Timothée Lecomte

# This file is part of Friture.
#
# Friture is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as published by
# the Free Software Foundation.
#
# Friture is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Friture.  If not, see <http://www.gnu.org/licenses/>.

import sys
from pyaudio import PyAudio, paInt16
from numpy import transpose, log10, sqrt, ceil, linspace, arange
from PyQt4 import QtGui, QtCore, Qt
import PyQt4.Qwt5 as Qwt
from Ui_friture import Ui_MainWindow
import resource
import audiodata
import proc

#pyuic4 friture.ui > Ui_friture.py
#pyrcc4 resource.qrc > resource.py

#had to install pyqwt from source
#first : sudo ln -s libqwt-qt4.so libqwt.so
#then, in the pyqwt configure subdirectory (for ubuntu jaunty):
#python configure.py -Q ../qwt-5.1 -4 -L /usr/lib -I /usr/include/ --module-install-path=/usr/lib/python2.6/dist-packages/PyQt4/Qwt5
#make
#sudo make install

SAMPLING_RATE = 44100
NUM_SAMPLES = 1024
FRAMES_PER_BUFFER = NUM_SAMPLES
TIMER_PERIOD_MS = int(ceil(1000.*NUM_SAMPLES/float(SAMPLING_RATE)))
DEVICE_INDEX = 0

class Friture(QtGui.QMainWindow, Ui_MainWindow):
	def __init__(self):
		QtGui.QMainWindow.__init__(self)
		Ui_MainWindow.__init__(self)

		# Configure l'interface utilisateur.
		self.setupUi(self)
		
		self.toolBar.addAction(self.dockWidgetLevels.toggleViewAction())
		self.toolBar.addAction(self.dockWidgetScope.toggleViewAction())
		self.toolBar.addAction(self.dockWidgetSpectrum.toggleViewAction())
		self.toolBar.addAction(self.dockWidgetStatistics.toggleViewAction())

		self.i = 0
		self.losts = 0
		self.useless = 0
		self.spec_min = -100.
		self.spec_max = -20.
		self.fft_size = 256
		self.max_in_a_row = 1

		print "Initializing PyAudio"
		self.pa = PyAudio()

		self.set_devices_list()
		device_count = self.get_device_count()
		default_device_index = self.get_default_input_device()
		
		# we will try to open all the devices until one works, starting by the default input device
		devices = range(0, device_count)
		devices.remove(default_device_index)
		devices = [default_device_index] + devices

		for index in devices:
			print "Opening the stream"
			self.stream = self.pa.open(format=paInt16, channels=1, rate=SAMPLING_RATE, input=True,
			frames_per_buffer=FRAMES_PER_BUFFER, input_device_index=index)
			self.device_index = index

			print "Trying to read from input device #%d" % (index)
			if self.try_input_device():
				print "Success"
				lat_ms = 1000*self.stream.get_input_latency()
				self.max_in_a_row = int(ceil(lat_ms/TIMER_PERIOD_MS))
				break
			else:
				print "Fail"

		self.comboBox_inputDevice.setCurrentIndex(self.device_index)

		self.procclass = proc.ProcClass()
		self.canvasscaledspectrogram = audiodata.CanvasScaledSpectrogram()
		self.dest_pixmap = QtGui.QPixmap(600, 300)
		self.dest_pixmap.fill()
		self.painter = QtGui.QPainter(self.dest_pixmap)

		print "Setting up the timer, will fire every %d ms" %(TIMER_PERIOD_MS)
		self.timer = QtCore.QTimer()
		#timer that fires roughly every 20 ms
		self.timer.setInterval(TIMER_PERIOD_MS)

		self.connect(self.actionStart, QtCore.SIGNAL('triggered()'), self.timer_toggle)
		
		self.connect(self.comboBox_freqscale, QtCore.SIGNAL('currentIndexChanged(int)'), self.freqscalechanged)
		self.connect(self.comboBox_fftsize, QtCore.SIGNAL('currentIndexChanged(int)'), self.fftsizechanged)
		self.connect(self.spinBox_specmax, QtCore.SIGNAL('valueChanged(int)'), self.specrangechanged)
		self.connect(self.spinBox_specmin, QtCore.SIGNAL('valueChanged(int)'), self.specrangechanged)
		self.connect(self.comboBox_inputDevice, QtCore.SIGNAL('currentIndexChanged(int)'), self.input_device_changed)
		self.connect(self.timer, QtCore.SIGNAL('timeout()'), self.timer_slot)
		self.connect(self.PlotZoneImage, QtCore.SIGNAL('pointerMoved'), self.pointer_moved)
		self.connect(self.PlotZoneSpect, QtCore.SIGNAL('pointerMoved'), self.pointer_moved)
		self.connect(self.PlotZoneUp, QtCore.SIGNAL('pointerMoved'), self.pointer_moved)

		self.timer_toggle()
		print "Done"

	def pointer_moved(self, info):
		self.statusBar.showMessage(info)

	#return True on success
	def try_input_device(self):
		n_try = 0
		while self.stream.get_read_available() < NUM_SAMPLES and n_try < 1000000:
			n_try +=1

		if n_try == 1000000:
			return False
		else:
			lat_ms = 1000*self.stream.get_input_latency()
			print "Device claims %d ms latency" %(lat_ms)
			return True

	def timer_toggle(self):
		if self.timer.isActive():
			self.timer.stop()
		else:
			self.timer.start()
			
	def scope_toggle(self):
		if self.dockWidgetScope.isVisible():
			self.dockWidgetScope.hide()
		else:
			self.dockWidgetScope.show()

	def spectrum_toggle(self):
		if self.dockWidgetSpectrum.isVisible():
			self.dockWidgetSpectrum.hide()
		else:
			self.dockWidgetSpectrum.show()

	def statistics_toggle(self):
		if self.dockWidgetStatistics.isVisible():
			self.dockWidgetStatistics.hide()
		else:
			self.dockWidgetStatistics.show()

	def levels_toggle(self):
		if self.dockWidgetLevels.isVisible():
			self.dockWidgetLevels.hide()
		else:
			self.dockWidgetLevels.show()

	def timer_slot(self):
		j = 0
		if self.stream.get_read_available() < NUM_SAMPLES:
			self.useless += 1
			return
		
		while self.stream.get_read_available() >= NUM_SAMPLES:
			j += 1
			rawdata = self.stream.read(NUM_SAMPLES)
			if j < self.max_in_a_row:
				self.process_data(rawdata)
			else:
				self.losts += 1

	def process_data(self, rawdata):
		channels = 1
		format = paInt16
		rate = SAMPLING_RATE
		adata = audiodata.AudioData(rawdata = rawdata,
					nchannels = channels,
					format = format,
					samplesize = self.pa.get_sample_size(format),
					samplerate = rate)

		self.i += 1
		time = adata.floatdata
		level_rms = 20*log10(sqrt((time**2).sum()/len(time)*2.) + 0*1e-80) #*2. to get 0dB for a sine wave
		level_max = 20*log10(abs(time).max() + 0*1e-80)
		level_label = "Chunk #%d\nLost chunks: %d = %.01f %%\nUseless timer wakeups: %d = %.01f %%" % (self.i, self.losts, self.losts*100./float(self.i), self.useless, self.useless*100./float(self.i))
		self.LabelLevel.setText(level_label)
		self.label_rms.setText("%.01f" % level_rms)
		self.label_peak.setText("%.01f" % level_max)

		self.meter.setValue(0, sqrt((time**2).sum()/len(time)*2.))
		self.meter.setValue(1, abs(time).max())

		signal = adata.floatdata
		time = linspace(0., len(signal)/float(rate), len(signal))
		
		self.PlotZoneUp.setdata(time, signal)

		sp = self.procclass.process(adata, self.fft_size)
		if sp == None:
			return

		clip = lambda val, low, high: min(high, max(low, val))
		# scale the db spectrum from [- spec_range db ... 0 db] > [0..1]
		epsilon = 1e-30
		db_spectrogram = (20*log10(sp + epsilon))
		norm_spectrogram = (db_spectrogram.clip(self.spec_min, self.spec_max) - self.spec_min)/(self.spec_max - self.spec_min)

		if db_spectrogram.ndim == 1:
			y = db_spectrogram.transpose()
		else:
			y = db_spectrogram[0,:].transpose()
		freq = linspace(0., 22050., len(y))
		self.PlotZoneSpect.setdata(freq, y)
		self.PlotZoneImage.addData(norm_spectrogram.transpose())

	def fftsizechanged(self, index):
		print "fft_size_changed slot", index, 2**index*32, 150000/self.fft_size
		self.fft_size = 2**index*32

	def freqscalechanged(self, index):
		print "freq_scale slot", index
		if index == 1:
			self.PlotZoneSpect.setlogfreqscale()
			self.PlotZoneImage.setlogfreqscale()
		else:
			self.PlotZoneSpect.setlinfreqscale()
			self.PlotZoneImage.setlinfreqscale()

	def specrangechanged(self, value):
		self.spec_max = self.spinBox_specmax.value()
		self.spec_min = self.spinBox_specmin.value()

	def set_devices_list(self):
		default_device_index = self.get_default_input_device()
		device_count = self.get_device_count()
		
		for i in range(0, device_count):
			dev = self.pa.get_device_info_by_index(i)
			api = self.pa.get_host_api_info_by_index(dev['hostApi'])['name']
			desc = "%d: (%s) %s" %(dev['index'], api, dev['name'])
			if i == default_device_index:
				desc += ' (system default)'			
			self.comboBox_inputDevice.addItem(desc)

	def get_default_input_device(self):
		return self.pa.get_default_input_device_info()['index']
	
	def get_device_count(self):
		return self.pa.get_device_count()

	def input_device_changed(self, index):
		self.timer.stop()
		# FIXME update to toolbar action
		# self.pushButton_startstop.setChecked(False)
		
		# save current stream in case we need to restore it
		previous_stream = self.stream

		self.stream = self.pa.open(format=paInt16, channels=1, rate=SAMPLING_RATE, input=True,
                     frames_per_buffer=FRAMES_PER_BUFFER, input_device_index=index)

		print "Trying to read from input device #%d" % (index)
		if self.try_input_device():
			print "Success"
			previous_stream.close()
			self.device_index = index
		else:
			print "Fail"
			error_message = QtGui.QErrorMessage(self)
			error_message.setWindowTitle("Input device error")
			error_message.showMessage("Impossible to use the selected device, reverting to the previous one")
			self.stream.close()
			self.stream = previous_stream
			self.comboBox_inputDevice.setCurrentIndex(self.device_index)
		
		lat_ms = 1000*self.stream.get_input_latency()
		self.max_in_a_row = int(ceil(lat_ms/TIMER_PERIOD_MS))
		
		self.timer.start()
		# FIXME update to toolbar action
		# self.pushButton_startstop.setChecked(True)

if __name__ == "__main__":
	app = QtGui.QApplication(sys.argv)

	pixmap = QtGui.QPixmap(":/splash.png")
	splash = QtGui.QSplashScreen(pixmap)
	splash.show()
	splash.showMessage("Initializing the audio subsystem")
	app.processEvents()
	window = Friture()
	window.show()
	splash.finish(window)
	
	profile = True
	
	if profile:
		import cProfile
		import lsprofcalltree

		p = cProfile.Profile()
		p.run('app.exec_()')
		k = lsprofcalltree.KCacheGrind(p)
		data = open('prof.kgrind.out.00000', 'w+')
		k.output(data)
		data.close()
		sys.exit(0)
	else:
		sys.exit(app.exec_())
