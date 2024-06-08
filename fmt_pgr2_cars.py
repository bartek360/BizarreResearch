from inc_noesis import *
import noesis
import rapi
import zlib


def registerNoesisTypes():
	handle = noesis.register("Project Gotham Racing 2 Vehicle Models!", ".pak_opn;.pak_hrd;.pak_sft")
	noesis.setHandlerTypeCheck(handle, noepyCheckType)
	noesis.setHandlerLoadModel(handle, noepyLoadModel)

	return 1

def noepyCheckType(data):
	return tr(data[0:4]) in ('INDX', 'MESH')

def bit_vector(val, start, count):
	return (val >> start) & (1 << count) - 1

def tr(s):
	try:
		_ = s[:s.index(b'\0')]
	except ValueError:
		_ = s
	return _.decode('ascii')
stride = 14
class GothFILE:
	def __init__(self):
		self.lods = []
		self.materials = []
		self.textures = []

	def verify(self, bs):
		return 1

	def parse(self, stream):
		self.bs = stream
		bs = self.bs
		self.pakToc = {}

		pgr_header = tr(bs.readBytes(4))
		if pgr_header == 'INDX':
			pakSize, pakNumFiles = bs.read('4x2L')
			for i in range(pakNumFiles):
				cnkType, cnkSize, cnkOffset = bs.read('4s4x2L')
				self.pakToc[tr(cnkType)] = [cnkSize,cnkOffset+0xC,None]
		elif pgr_header == 'MESH':
			bs.seek(0)
			while True:
				cnkType = tr(*bs.read('4s'))
				if cnkType == 'END':
					break
				cnkSize = bs.read('4xL')[0]
				cnkOffset = bs.tell()
				self.pakToc[(cnkType)] = [cnkSize,cnkOffset,None]
				bs.seek(cnkSize & 0x3ffffff, NOESEEK_REL)
		else:
			noesis.doException('Unexpected header %s' % pgr_header.decode())
		for c in self.pakToc.values():
			bs.seek(c[1])
			if c[0] & 0xC0000000:
				unpak_size = bs.readUInt()
				zsize = (c[0] & 0x3ffffff)
				buf = bs.readBytes(zsize-4) 
				zobj = zlib.decompressobj(15)
				c[2] = zobj.decompress(buf)
			else:
				c[2] = bs.readBytes(c[0])


def split_index_buffer(lst):
    split_lists = []
    current_list = [lst[0]]
    
    for i in range(1, len(lst)):
        if lst[i] == lst[i-1]:
            split_lists.append(current_list)
            current_list = [lst[i]]
        else:
            current_list.append(lst[i])
    if current_list:
        split_lists.append(current_list)
    return split_lists

uid = 0
PAKFLAG_ALIGN16 = 0
class GothGROUP:
	def __init__(self):
		self.grp_pos = None
		self.subs = []
		self.parentSize = 0
		self.children = []
		self.name = ""

	def parse(self, stream, mysize):
		self.bs = stream
		bs = self.bs
		
		global uid
		self.uid = uid
		uid += 1

		struct_start = bs.tell()

		self.parentSize = bs.readInt()
		self.childSize = bs.readInt()

		zzsize = self.childSize or self.parentSize or mysize

		# 3125 - no damage part??
		self.ggUnk1 = bs.readUShort()
		ggNumV = bs.readUShort()

		self.grp_pos = NoeVec3(bs.read('4f')[:3])
		grp_scale = NoeVec3(bs.read('3f'))

		ggSubsPerLOD = bs.readUShort()
		ggNumF = bs.readUShort()
		self.subsPerLOD = ggSubsPerLOD


		ggUnk3 = bs.readUShort()
		ggFlags = bs.readUShort()
		ggExtVbuffO = bs.readUInt()

		self.vbo = ggExtVbuffO
		self.numVerts = ggNumV

		if ggNumF:
			self.indexBuffer = bs.readBytes(2 * (ggNumF + (ggNumF%2)))

		if ggExtVbuffO != 0xFFFFFFFF:
			fff = ggNumF
			while fff > 0:
				sub = {'matId': bs.readUShort(), 'type': bs.readUShort(), 'startIdx': bs.readUShort(), 'count': bs.readUShort()}
				self.subs.append( sub )
				fff -= sub['count']
		struct_end = bs.tell()
		curr_size = zzsize - (struct_end - struct_start)
		if curr_size > 0:
			global PAKFLAG_ALIGN16
			paddd = curr_size % PAKFLAG_ALIGN16
			bs.readBytes(paddd)
			curr_size -= paddd
			if curr_size > 1000000 or curr_size < 0:
				noesis.doException("Abnormal curr_size" + str(curr_size))
			self.name = tr(bs.readBytes(curr_size))
		if self.childSize != 0:
			x = self.parentSize - self.childSize
			while x > 0:
				child = GothGROUP()
				child.parse(bs, x)
				x -= child.sizeof
				self.children.append(child)

		self.sizeof = bs.tell() - struct_start
		return zzsize

class GothLOD:
	def __init__(self):
		self.groups = []

	def parse(self, stream):
		self.bs = stream
		bs = self.bs

		mysize = self.bs.getSize()

		while True:
			group = GothGROUP()
			tempsz =  group.parse(bs, mysize)
			mysize -= group.sizeof
			
			self.groups.append(group)
			if group.parentSize == 0:
				break

class GothINFO:
	def __init__(self):
		pass
	
	def parse(self, bs):
		self.whlRearSide = bs.readFloat()
		self.whlFrontSide = bs.readFloat()
		self.whlFront = bs.readFloat()
		self.whlRear = bs.readFloat()
		self.scaleX = bs.readFloat()
		self.scaleY = bs.readFloat()
	
def FlipTriangleStripInArray(values, begIndex, endIndex):
	count = endIndex - begIndex
	if count < 3:
		return
	# Number of elements (and triangles) is odd: Reverse elements.
	if count % 2:
		values[begIndex:endIndex] = values[begIndex:endIndex][::-1]
	# Number of elements (and triangles) is even: Repeat first element.
	else:
		values.insert(begIndex, values[begIndex])

def noepyLoadModel(data, mdlList):
	bs = NoeBitStream(data)

	noeTextures = []
	noeMaterials = []
	
	matBinds = []

	# parse file
	metFile = GothFILE()
	metFile.parse(bs)
	bs = NoeBitStream(metFile.pakToc['MESH'][2])
	
	global PAKFLAG_ALIGN16
	PAKFLAG_ALIGN16 = 16 if metFile.pakToc['MESH'][0] & 0x40000000 else 4

	lod = GothLOD()
	lod.parse(bs)
	metFile.lods.append(lod)
	
	MAT43 = NoeMat43()
	MAT43[0] = -MAT43[0]

	gpuData = metFile.pakToc['GPUD'][2]
	ts = NoeBitStream(metFile.pakToc['TEXT'][2])
	ms = NoeBitStream(metFile.pakToc['MAT'][2])
	ins = NoeBitStream(metFile.pakToc['INFO'][2])
	g_Info = GothINFO()
	g_Info.parse(ins)
	
	
	
	matcount = ms.readUInt()
	for i in range(matcount):
		texid = ms.readShort()
		maybeColor = ms.readUShort()
		flags1 = ms.readUShort()
		flags2 = ms.readUByte()
		const1C = ms.readUByte()
		
		matBinds.append((texid,flags1,flags2))
	unkcount = ms.readUInt()
	ms.seek(unkcount * 4, NOESEEK_REL)
	mp1,mp2,mp3,mp4 = ms.read('4h')
	
	texcount = ts.readUInt()
	for i in range(texcount):
		bname = ts.readBytes(32)
		
		texname = noeStrFromBytes(bname)
		format = ts.readUShort()
		sizes = ts.readUShort()
		offset = ts.readUInt()
		
		height = 2**(sizes & 0xF)
		width = 2**((sizes & 0xf0) >> 4)
		

		sourceData = rapi.imageDecodeDXT(gpuData[offset:], width, height, noesis.NOESISTEX_DXT5)
		for i in range(width * height):
			sourceData[i*4+3] = 0xFF if sourceData[i*4+3] != 0 else 0

		newTexture = NoeTexture(texname, width, height, sourceData, noesis.NOESISTEX_RGBA32)
		noeTextures.append(newTexture)
		material = NoeMaterial("mat_" + texname, "")
		material.setTexture(texname)
		noeMaterials.append(material)

	vbData = metFile.pakToc['VB'][2]

	factor = 32
	
	scaleX = factor/10*g_Info.scaleX
	scaleY = factor/10*g_Info.scaleY
	
	scale = NoeVec3((-factor*g_Info.scaleX,factor*g_Info.scaleY,factor*g_Info.scaleY))
	vecFL = NoeVec3((g_Info.whlFrontSide*scaleX,0,g_Info.whlFront*scaleY))
	vecFR = NoeVec3((-g_Info.whlFrontSide*scaleX,0,g_Info.whlFront*scaleY))
	vecBL = NoeVec3((g_Info.whlRearSide*scaleX,0,g_Info.whlRear*scaleY))
	vecBR = NoeVec3((-g_Info.whlRearSide*scaleX,0,g_Info.whlRear*scaleY))

	vbOffset = int.from_bytes(vbData, byteorder='little')
	for lod in metFile.lods:
		ctx = rapi.rpgCreateContext()
		for xD in lod.groups:
			def parse_group(modl, parentId):
				for c in modl.children:
					parse_group(c, parentId)
				if modl.numVerts == 0:
					rapi.rpgSetName(str(modl.uid) + '_childof_' + str(parentId))
					print(str(modl.uid) + '_childof_' + str(parentId) + modl.name)
					rapi.rpgSetMaterial('')
					rapi.immBegin(noesis.RPGEO_POINTS)
					rapi.immUV2((0,0))
					rapi.immVertex3(modl.grp_pos.getStorage())
					rapi.immEnd()
					return
				vb = gpuData[vbOffset + modl.vbo:]
				vbs = NoeBitStream(vb)
				rapi.rpgSetTransform(MAT43)
				if modl.name.endswith("FL"):
					rapi.rpgSetPosScaleBias(scale, vecFL)
				elif modl.name.endswith("FR"):
					rapi.rpgSetPosScaleBias(scale, vecFR)
				elif modl.name.endswith("BL"):
					rapi.rpgSetPosScaleBias(scale, vecBL)
				elif modl.name.endswith("BR"):
					rapi.rpgSetPosScaleBias(scale, vecBR)
				else:
					rapi.rpgSetTransform(None)
					rapi.rpgSetPosScaleBias(scale, None)

				ibs = NoeBitStream(modl.indexBuffer)
				for it,sub in enumerate(modl.subs[:modl.subsPerLOD]):
					mbTexId,mbFlags1,mbFlags2 = matBinds[sub['matId']]
					realid = mbTexId
					objName = str(modl.uid) + '_childof_' + str(parentId) + '_' + modl.name + "_mat" + str(sub['matId'])
					rapi.rpgSetName(objName)
					if modl.name == "WIN":
						rapi.rpgSetMaterial('glass0')
					elif realid < 0:
						rapi.rpgSetMaterial('NOTEXTURE')
					else:
						if mbFlags1 & 4:
							rapi.rpgSetMaterial('colored_' + noeMaterials[realid].name)
						else:
							rapi.rpgSetMaterial(noeMaterials[realid].name)
					si = 2*sub['startIdx']

					
					ibs.seek(si)
					bufs = [[ibs.readUShort() for idx in range( sub['count'] )]]

					# 8 - numberplates and badges
					# 4 - everything but interior
					# 2 - unknown
					# 1 - not scratches, wheels or interior
					for triIdx, idc in enumerate(bufs):
						if modl.name.endswith(('FL','FR','BL','BR')):
							FlipTriangleStripInArray(idc,0,len(idc))
						rapi.immBegin(noesis.RPGEO_TRIANGLE_STRIP)
						for i,val in enumerate(idc):
							uv = noeUnpack('hh', vb[val*stride+10:val*stride+10+4])
							nrm, = noeUnpack('<L', vb[val*stride+6:val*stride+6+4])
							pnx = (bit_vector(nrm,0,11))-1024
							pny = (bit_vector(nrm,11,11))-1024
							pnz = (bit_vector(nrm,22,10))-512
							if pnx < 0:
								pnx += 2047
							if pny < 0:
								pny += 2047
							if pnz < 0:							
								pnz += 1023
							f=100/0xFFFF
							pnx /= 2047
							pny /= 2047
							pnz /= 1023
							rapi.immUV2( (uv[0]*f,uv[1]*f ) )
							rapi.immNormal3((2*pnx-1,2*pny-1,2*pnz-1))
							rapi.immVertex3s(vb, val*stride)
						rapi.immEnd()
						rapi.rpgClearBufferBinds()
			parse_group(xD,xD.uid)
		rapi.rpgOptimize()
		mdl = rapi.rpgConstructModelSlim()
		wndMat = NoeMaterial("glass0", "")
		wndTex = NoeTexture("glass0", 2, 2, b'\0\0\0\x70' * 4)
		wndMat.setTexture("glass0")
		wndMat.setDiffuseColor(NoeVec4([1.0,1.0,1.0,100 / 255]))
		noeMaterials.append(wndMat)
		noeTextures.append(wndTex)
			
		x = len(noeMaterials)-1
		for i in range(x):
			clr = NoeMaterial('colored_' + noeMaterials[i].name, noeMaterials[i].texName)
			clr.flags = noeMaterials[i].flags
			clr.setDiffuseColor(NoeVec4([0.0,1.0,1.0,100 / 255]))
			noeMaterials.append(clr)
			
		wndMat.setFlags(noesis.NMATFLAG_TWOSIDED | noesis.NMATFLAG_SORT01)

		mdl.setModelMaterials(NoeModelMaterials(noeTextures, noeMaterials))
		mdlList.append(mdl)
	return 1