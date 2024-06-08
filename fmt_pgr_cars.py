from inc_noesis import *
import noesis
import rapi

def registerNoesisTypes():
	handle = noesis.register("Project Gotham Racing Vehicle Models", ".hrd;.nrm;.sft;.hrd_cth;.nrm_cth;.sft_cth;.hrd_F;.nrm_F;.sft_F")
	noesis.setHandlerTypeCheck(handle, noepyCheckType)
	noesis.setHandlerLoadModel(handle, noepyLoadModel)

	return 1

def noepyCheckType(data):
	bs = NoeBitStream(data)
	mf = GothFILE()
	test = mf.verify(bs)
	return test
	
stride = 24
class GothFILE:
	def __init__(self):
		self.lods = []
		self.materials = []
		self.textures = []
		
	def verify(self, bs):
		mfPropSize = bs.readUInt()
		if mfPropSize != 452:
			noesis.logError("Unexpected prop chunk size {}. Maybe different build?\n".format(mfPropSize))
			return 0
		bs.seek( mfPropSize, NOESEEK_ABS )
		texOffset = bs.readUInt()
		flags = bs.readUInt()
		if (flags == 0 or flags > 255):
			return 0
		return 1
	
	def parse(self, stream):
		self.bs = stream
		bs = self.bs
		
		header_size = bs.readUInt()
		bs.seek( 92, NOESEEK_ABS )
		self.whlWidth, self.whlFront,self.whlRear = bs.read('3f')
		bs.seek( header_size, NOESEEK_ABS )
		texOffset = bs.readUInt()
		flags = bs.readUInt()
		if (flags == 0):
			return 0
		if (not flags & 1):
			reserved = bs.readInt()
		
		numLODs = bool(flags & 2) + bool(flags & 4) + bool(flags + 8) + bool(flags & 0x10) + bool(flags & 0x20)
		for i in range(numLODs):
			lod = GothLOD()
			lod.parse(bs)
			self.lods.append(lod)
			
		
		bs.seek(texOffset)
		numTextures = bs.readUInt()

		if rapi.getInputName().endswith("_F"):
			resBufferPath = rapi.getInputName()[:-2] + "_res"
		else:
			resBufferPath = rapi.getInputName() + "_res"
		print(resBufferPath)
		if rapi.checkFileExists(resBufferPath):
			resBufferData = rapi.loadIntoByteArray(resBufferPath)

		
		for i in range(numTextures):
			texname = bs.readBytes(32).split(b'\0')[0].decode('ascii')
			width = bs.readUShort()
			height = bs.readUShort()
			format1 = bs.readUShort()
			format2 = bs.readUShort()
			texOffset = bs.readUInt()
			
			
			if format1 == 10 and format2 == 8:
				fmt = noesis.NOESISTEX_DXT5
				divisor = 4
			elif format1 == 6 and format2 == 0:
				fmt = noesis.NOESISTEX_DXT1
				divisor = 8
			
			
			mapSize = width * height * 4 // divisor
			
			
			
			d = rapi.imageDecodeDXT(resBufferData[texOffset:texOffset+mapSize], width, height, fmt)
			numPixels = width * height
			if format1 == 10 and format2 == 8:
				for i in range(numPixels):
					d[i*4+3] = 0xFF if d[i*4+3] != 0 else 0
			newTexture = NoeTexture(texname, width, height, d, noesis.NOESISTEX_RGBA32)
			newTexture.flags |= noesis.NTEXFLAG_WRAP_CLAMP
			self.textures.append(newTexture)
			material = NoeMaterial("mat_" + texname, "")
			material.setTexture(texname)
			material.setAlphaTest(0)
			self.materials.append(material)
		wndMat = NoeMaterial("glass0", "")
		wndTex = NoeTexture("glass0", 2, 2, b'\0\0\0\x70' * 4)
		wndMat.setTexture("glass0")
		wndMat.setDiffuseColor(NoeVec4([1.0,1.0,1.0,100 / 255]))
		wndMat.setFlags(noesis.NMATFLAG_SORT01)
		self.materials.append(wndMat)
		self.textures.append(wndTex)

class GothGROUP:
	def __init__(self):
		self.grp_pos = None
		self.subs = []
		self.size = 0
	
	def parse(self, stream, mysize):
		self.bs = stream
		bs = self.bs
		
		struct_start = bs.tell()
		
		ggSize = bs.readUInt()
		self.size = ggSize
		ggReserved1 = bs.readUInt()
		
		self.grp_pos = NoeVec3((bs.readFloat(), bs.readFloat(), bs.readFloat()))
		bs.readInt()
		grp_scale = NoeVec3((bs.readFloat(), bs.readFloat(), bs.readFloat()))
		
		ggNumVerts = bs.readUShort()
		ggNumFaces = bs.readUShort()
		ggNumMats  = bs.readUShort()
		ggUnkShort = bs.readUShort()
		ggFlags    = bs.readUShort()
		ggNameLen  = bs.readUShort()
		
		ggReserved2 = bs.readUInt()
		ggReserved3 = bs.readUInt()
		ggExtVbuffO = bs.readUInt()
		
		self.nameLen = ggNameLen
		self.vbo = ggExtVbuffO
		self.numVerts = ggNumVerts
		
		self.indexBuffer = bs.readBytes(2 * ggNumFaces)
		
		ggNumFaces *= 2
		
		pad = bs.readBytes( (4 - (ggNumFaces % 4)) % 4 )
		
		for i in range(ggNumMats):
			self.subs.append( {'matId': bs.readUShort(), 'type': bs.readUShort(), 'startIdx': bs.readUShort()*2, 'count': bs.readUShort()} )
		
		if self.nameLen:
			name = bs.readBytes(self.nameLen).split(b'\0')[0].decode('ascii')
			self.name = name
		
		struct_end = bs.tell()
			
		pad2 = bs.readBytes( (4 - (struct_end - struct_start % 4)) % 4 )
		
		return ggSize

class GothLOD:
	def __init__(self):
		self.groups = []
		
	def parse(self, stream):
		self.bs = stream
		bs = self.bs
		
		next_mesh = bs.readUInt()
		# MESHinfo
		rel_texture_offset = bs.readUInt()
		grp_count = bs.readUInt()
		tex_count = bs.readUInt()
		rel_next_mesh_offset = bs.readUInt()
		bs.seek(8, NOESEEK_REL)
		mysize = rel_next_mesh_offset
		for i in range(grp_count):
			group = GothGROUP()
			mysize -= group.parse(bs, mysize)
			self.groups.append(group)
			if group.size == 0:
				break

class GothSUB:
	def __init__(self):
		self.vtxData = None
		self.matId = 0
		self.strips = []
	
	def parse(self, stream):
		self.bs = stream
		bs = self.bs
						
		struct_start = bs.tell()
		self.struct_size = bs.readInt()
		self.matId = bs.readInt()
		verts_count = bs.readInt()
		unknown_nil = bs.readInt()
		
		self.vtxData = bs.readBytes(stride * verts_count)
		while True:
			triLength = bs.readUShort()
			if triLength < 1:
				break
			self.strips.append((bs.readBytes(2 * triLength), triLength))
		no = bs.tell() - struct_start
		bs.seek((8 - (no % 8)) % 8, NOESEEK_REL)
		struct_end = bs.tell()
		return struct_end - struct_start

def noepyLoadModel(data, mdlList):
	bs = NoeBitStream(data)
	
	noeTextures = []
	noeMaterials = []
	
	# parse file
	metFile = GothFILE()
	metFile.parse(bs)
	
	vtxBufferPath = rapi.getInputName() + "_v"
	if rapi.checkFileExists(vtxBufferPath):
		vtxBufferData = rapi.loadIntoByteArray(vtxBufferPath)

	scaleX,scaleY = 1,1
	vecFL = NoeVec3((-metFile.whlWidth*scaleX,0,metFile.whlFront*scaleY))
	vecFR = NoeVec3((metFile.whlWidth*scaleX,0,metFile.whlFront*scaleY))
	vecBL = NoeVec3((-metFile.whlWidth*scaleX,0,metFile.whlRear*scaleY))
	vecBR = NoeVec3((metFile.whlWidth*scaleX,0,metFile.whlRear*scaleY))

	
	for lod in metFile.lods:
		ctx = rapi.rpgCreateContext()
		for group in lod.groups:
			vb = vtxBufferData[group.vbo:group.vbo + group.numVerts * stride]
			rapi.rpgBindPositionBufferOfs(vb, noesis.RPGEODATA_FLOAT, stride, 0)
			rapi.rpgBindUV1BufferOfs(vb, noesis.RPGEODATA_FLOAT, stride, 16)
			useWndMat = False
			useNPMat = False
			if group.nameLen:
				if group.name in ("SCR") or group.name.endswith("_D"):
					continue
				rapi.rpgSetName(group.name)
				
				useWndMat = group.name in ("WIN","WSM",'WS2','WSD') or group.name.startswith('HLG')
				useNPMat = group.name in ('NP','NP2')
				
				if group.name.endswith("FL"):
					rapi.rpgSetPosScaleBias(None, vecFL)
				elif group.name.endswith("FR"):
					rapi.rpgSetPosScaleBias(None, vecFR)
				elif group.name.endswith("BL"):
					rapi.rpgSetPosScaleBias(None, vecBL)
				elif group.name.endswith("BR"):
					rapi.rpgSetPosScaleBias(None, vecBR)
				else:
					rapi.rpgSetPosScaleBias(None, group.grp_pos)
			else:
				rapi.rpgSetPosScaleBias(None,group.grp_pos)
			for sub in group.subs:
				if useWndMat:
					rapi.rpgSetMaterial('glass0')
				elif useNPMat:
					rapi.rpgSetMaterial('mat_NumPlate')
				else:
					rapi.rpgSetMaterial(metFile.materials[sub['matId']].name)

				rapi.rpgCommitTriangles( group.indexBuffer[sub['startIdx']:sub['startIdx']+2*(sub['count']+2)], noesis.RPGEODATA_USHORT, 
				sub['count']+2, noesis.RPGEO_TRIANGLE_STRIP, 1)
		mdl = rapi.rpgConstructModel()
		mdl.setModelMaterials(NoeModelMaterials(metFile.textures, metFile.materials))
		mdlList.append(mdl)
	return 1