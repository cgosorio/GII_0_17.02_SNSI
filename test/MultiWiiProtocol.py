'''
Author: Mario Bartolomé
Date: Jan 24, 2018
######

This file aims to provide a simple class to implement MSP protocol.
'''

import serial
import time
import struct


class MSPio:
	"""
	This class provides a quick implementation to get and send data to a serial port using MSP protocol.

	"""

	message = {'preamble': [b'$',b'M'],
	           'toFC': [b'<'],
	           'fromFC': [b'>'],
	           }

	###  Supported codes
	MSP_MOTOR = 104             # GET µs being write to the motors. (8 motors returned u2bytes each)
	MSP_RC = 105                # GET RC channel reading (18 channel returned u2bytes each).
	MSP_ATTITUDE = 108          # GET attitude (angle x, angle y, heading).
	MSP_ANALOG = 110            # GET status (battery voltage, consumed power, RSSI, instant current).
	MSP_SET_RAW_RC = 200        # SET rc input (injects RC channel, overriding RX input if upd. every second)
	MSP_SET_RAW_MOTOR = 214     # SET individual motor value [1000 , 2000]

	###  Parsing schemes for struct function:
	#   < : Little Endian
	#   number : Amount of ...
	#       H  : Unsigned int16_t (2Bytes)
	#       B  : Unsigned char (1Byte)

	MOTOR_PARSE = '<8H'
	RC_PARSE = '<18H'
	ATTITUDE_PARSE = '<3h'
	STATUS_PARSE = '<B3H'
	RC_SET_PARSE = None
	def __init__(self, serial_port='/dev/tty.SLAB_USBtoUART', baud_rate=115200):
		"""
		Constructor method for MSPio class.

		:param serial_port: The port to connect to. Defaults to '/dev/tty.SLAB_USBtoUART'.
		:param baud_rate: Speed of the connection in bauds. Defaults to 115200.
		"""
		self._serial = serial.Serial()
		self._serial.port = serial_port
		self._serial.baudrate = baud_rate

		try:
			self._serial.open()
			print("Port {0} successfully opened".format(serial_port))
		except serial.SerialException as err:
			print("Error while opening serial comm: {0}".format(str(err)))
		except FileNotFoundError as err:
			print("Can't find port to open: {0}".format(str(err)))


	def isOpen(self):
		"""
		Checks if serial communication is open.

		:return: True if comm was open, False otherwise.
		"""
		return self._serial.isOpen()

	def close(self):
		"""
		Closes the communication if it was open.

		"""
		if self.isOpen():
			print("WARNING: Device will enter FAILSAFE mode!")
			self._serial.close()


	def cleanup(self):
		"""
		Cleans up the remaining buffers.
		:return:
		"""
		self._serial.flushInput()
		self._serial.flushOutput()


	def sendCMD(self, command, data=None, size=0):
		"""
		Sends the given command.

		:param command: The command to send.
		:param data: The data to send. Defaults to an empty list.
		:param size: Size of the data. Defaults to 0.
		"""

		if data is None:
			data = []
		checksum = 0
		msg = self.message['preamble'] + self.message['toFC'] + [size] + [command] + data

		# Checksum calc is XOR between <size>, <command> and (each byte) <data>
		msg = struct.pack('<3c2B%iH' % len(data), *msg)

		for i in msg[3:]:
			checksum ^= i
		# Add checksum at the end of the msg
		msg += bytes([checksum])
		try:
			self._serial.write(msg)
		except serial.SerialException as err:
			print("Could not write to port: {0}".format(str(err)))


	def readResponse(self, command, parse_to=None) -> (bytes, bool):
		"""
		Read FC's response. Remember to use this AFTER calling sendCMD.

		:param command: The command that was sent previously.
		:param parse_to: The format of the response. Defaults to None. If none, raw data to be returned
		:return: FC's response applying parsing method given.
		"""

		response = b''
		status_ok = False
		try:
			if self.isOpen():
				if self._serial.read(3) == b'$M>':  # Seems like a good answer...
					length = struct.unpack('<b', self._serial.read(1))[0]
					response_command = struct.unpack('<B', self._serial.read(1))[0]
					if response_command == command:  # and a good command response...
						response = self._serial.read(length)
						if parse_to is not None:
							response = struct.unpack(parse_to, response)
						status_ok = True
						self._serial.read(1) # Checksum... just to clean up the buffer
					else:
						print('<readResponse> to {0}: FC seems to be responding to some other command: {1}'.format(command, response_command))
				else:
					print("<readResponse>: Cant' get a good answer from FC when looking for {0} command".format(command))

		except serial.SerialException as err:

			print("Can't read from port: {0}".format(err))

		return response, status_ok


	def readAttitude(self) -> dict:
		"""
		Reads the attitude values from the IMU.
		Angle on X axis.
		Angle on Y axis.
		Heading of the device.

		:return: a dictionary containing those values, and a timestamp
		"""
		command = self.MSP_ATTITUDE

		attitude = {'x':0, 'y':0, 'heading':-361, 'timestamp':0}
		self.sendCMD(command)
		tmp, status_ok = self.readResponse(command, self.ATTITUDE_PARSE)
		if status_ok:
			attitude['x'] = tmp[0] / 10.0
			attitude['y'] = tmp[1]/10.0
			attitude['heading'] = tmp[2]
			attitude['timestamp'] = time.time()

		return attitude


	def readStatus(self) -> dict:
		"""
		Reads the analog sensors from the FC.
		Battery voltage.
		Consumed power.
		RSSI.
		Instant current.

		:return: a dictionary containing those values, and a timestamp
		"""
		command = self.MSP_ANALOG

		status = {'vbat': 0.0, 'cons_mah': 0, 'RSSI': 0, 'current': 0}
		self.sendCMD(command)
		tmp, status_ok = self.readResponse(command, self.STATUS_PARSE)
		if status_ok:
			status['vbat'] = tmp[0]/10
			status['cons_mah'] = tmp[1]
			status['RSSI'] = tmp[2]
			status['current'] = tmp[3]

		return status


	def arm(self):
		"""
		* **** WARNING! ****
				IN FACT, A HUGE ONE: NEVER EVER ARM THE DEVICE WITH THE PROPS ON UNLESS YOU KNOW WHAT YOU'RE DOING.
		(Or if need to chop something to pieces like... your fingers or whatever)

		Arms the device.

		"""

		command = self.MSP_SET_RAW_RC
		# All centered, but THROTTLE. AUX1 is arming. AUX2 is mode
		ROLL, PITCH, YAW, THROTTLE, AUX1, AUX2, AUX3, AUX4= 1500, 1500, 1500, 1000, 2000, 1000, 0, 0
		data = [ROLL, PITCH, YAW, THROTTLE, AUX1, AUX2, AUX3, AUX4]
		#self.sendCMDOLD(16, command, data)
		self.sendCMD(command, data, len(data) * 2)
		self.readResponse(command, self.RC_SET_PARSE)

	def setMotor(self, motors=None):
		"""
		* **** WARNING! ****
				IN FACT, A HUGE ONE: NEVER EVER MOVE THE MOTORS WITH THE PROPS ON UNLESS YOU KNOW WHAT YOU'RE DOING.
		(Or if need to chop something to pieces like... your fingers or whatever)

		Writes speed to motor.

		:param motors: A list containing the values to write to the motors. Max 8 motors. Defaults to a list of 1000's
		"""
		if motors is None:
			motors = [1000]*8

		command = self.MSP_SET_RAW_MOTOR
		if len(motors) <= 8:
			self.sendCMD(command, motors, len(motors)*2)
		else:
			print("Expected 'motors' parameter to have maximum 8 motors")


	def setRawRC(self, channels=None):
		"""
		Sends input to RC channels.

		:param channels: A list of values in µs to send.

		"""
		if channels is None:
			channels = [1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000]

		command = self.MSP_SET_RAW_RC

		if len(channels) <= 8:
			self.sendCMD(command, channels, len(channels)*2)
			self.readResponse(command, self.RC_SET_PARSE)
		else:
			print("Expected 'channels' parameter to have maximum 8 channels")



# To test it:
if __name__ == '__main__':
	ser = MSPio()
	import signal
	import sys
	def signal_handler(signal, frame):
		print('\nCleaning up...')
		ser.cleanup()

		ser.close()
		sys.exit(0)
	signal.signal(signal.SIGINT, signal_handler)

	if ser.isOpen():
		ser._serial.read_all()

		print("Give it a couple secs to fully init...")
		start = time.time()
		while time.time() - start < 2:
			print("Readings: {0} // Voltage: {1}".format(ser.readAttitude(), ser.readStatus()['vbat']))
			time.sleep(0.5)
			ser.setRawRC([1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000])

		# Getting about 25Hz refresh rate.
		print("Arming")
		start = time.time()
		while time.time() - start < 5:
			print("Readings: {0} // Voltage: {1}".format(ser.readAttitude(), ser.readStatus()['vbat']))
			ser.sendCMD(ser.MSP_MOTOR)
			print("Motors running at: {0}".format(ser.readResponse(ser.MSP_MOTOR, ser.MOTOR_PARSE)))
			ser.setRawRC([1500, 1500, 1000, 1500, 2000, 1000, 1000, 1000])
			# time.sleep(0.05)

		print("Disarming")
		while True:
			ser.setRawRC([1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000])
