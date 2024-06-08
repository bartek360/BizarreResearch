from inc_noesis import *
import noesis
import rapi

def registerNoesisTypes():
	handle = noesis.register("Metropolis Street Racer Vehicle Models", ".hrd;.nrm;.sft;.hrd_cth;.nrm_cth;.sft_cth;.hrd_fec;.nrm_fec;.sft_fec")
	noesis.setHandlerTypeCheck(handle, noepyCheckType)
	noesis.setHandlerLoadModel(handle, noepyLoadModel)

	return 1

def noepyCheckType(data):
	bs = NoeBitStream(data)
	mf = MetFILE()
	test = mf.verify(bs)
	return test

def makePVRHeader(datasize, width, height, format):
	#(a)rgb1555 by default
	pixFmt = 1
	#rgb565 if (format & 32768)
	if format & 32768:
		pixFmt = 1
	#argb1555 if (format & 65536)
	if format & 65536:
		pixFmt = 0
	#argb4444 if (format & 262144)
	if format & 262144:
		pixFmt = 2
	datFmt = 0xD if (format & 4) else 3
	pvrt = struct.pack('<4sllhh', b'PVRT', datasize, (datFmt << 8 | pixFmt), width, height)
	return pvrt


stride = 24

MSR_VER = {
	304 : "Nov 10, 1999 prototype",
	368 : "May  9, 2000 prototype",
	380 : "Retail / late prototype"
}
class MetFILE:
	def __init__(self):
		self.lods = []

	def verify(self, bs):
		mfPropSize = bs.readUInt()
		if mfPropSize not in MSR_VER:
			noesis.logError("Unexpected prop chunk size {}. Maybe different build?\n".format(mfPropSize))
			return 0
		noesis.logOutput(MSR_VER[mfPropSize])
		bs.seek( mfPropSize, NOESEEK_ABS )
		flags = bs.readUInt()
		if (flags == 0 or flags > 255):
			return 0
		return 1

	def parse(self, stream):
		self.bs = stream
		bs = self.bs

		header_size = bs.readUInt()
		bs.seek( header_size, NOESEEK_ABS )
		flags = bs.readUInt()
		if (flags == 0):
			return 0
		if (not flags & 1):
			reserved = bs.readInt()

		numLODs = bool(flags & 2) + bool(flags & 4) + bool(flags + 8) + bool(flags & 0x10) + bool(flags & 0x20)

		for i in range(numLODs):
			lod = MetLOD()
			lod.parse(bs)
			self.lods.append(lod)

class MetGROUP:
	def __init__(self):
		self.grp_pos = None
		self.subs = []

	def parse(self, stream, mysize):
		self.bs = stream
		bs = self.bs
		self.grp_pos = NoeVec3(bs.read('3f'))
		bs.readInt()
		grp_scale = NoeVec3((bs.readFloat(), bs.readFloat(), bs.readFloat()))

		grp_size = bs.readUInt()
		self.hasName = bs.readUInt()
		grp_nul = bs.readUInt()

		real_size = grp_size if (grp_size > 0) else (mysize - grp_size)
		real_size -= 40
		while real_size > 0:
			sub = MetSUB()
			self.subs.append(sub)
			real_size -= sub.parse(bs)
			if sub.struct_size == 0:
				break

		if self.hasName:
			name = bs.readBytes(real_size).split(b'\0')[0].decode('ascii')
			self.name = name
			real_size = 0
		return grp_size

class MetLOD:
	def __init__(self):
		self.groups = []
		self.materials = []
		self.textures = []

	def parse(self, stream):
		self.bs = stream
		bs = self.bs

		next_mesh = bs.readUInt()
		# MESHinfo
		rel_texture_offset = bs.readUInt()
		tex_count = bs.readUInt()
		grp_count = bs.readUInt()
		rel_next_mesh_offset = bs.readUInt()
		bs.seek(16, NOESEEK_REL)
		mysize = rel_texture_offset - 32
		for i in range(grp_count):
			group = MetGROUP()
			mysize -= group.parse(bs, mysize)
			self.groups.append(group)
		for i in range(tex_count):
			texsize = bs.readInt()
			texname = bs.readBytes(32).split(b'\0')[0].decode('ascii') + ".pvr"
			width = bs.readUShort()
			height = bs.readUShort()
			format = bs.readUInt()

			if format & 0x4000:
				print("{}: {}x{} F:{}".format(texname, width, height, format))

			if format & 4:
				datasize = width * height * 2
				data = bs.readBytes(datasize)
			else:
				datasize = width * height // 4
				codebook = bs.readBytes(2048)
				indices  = bs.readBytes(datasize)
				datasize += 2048
				data = codebook + indices

			header = makePVRHeader(datasize, width, height, format)

			decompTex = rapi.loadTexByHandler(header + data, ".pvr")
			sourceData = decompTex.pixelData if decompTex else None

			newTexture = NoeTexture(texname, width, height, sourceData, noesis.NOESISTEX_RGBA32)
			newTexture.flags |= noesis.NTEXFLAG_WRAP_CLAMP
			self.textures.append(newTexture)
			material = NoeMaterial("mat_" + texname, "")
			material.setTexture(texname)
			self.materials.append(material)

			if not format & 0x4000:
				continue

			if format & 4: # RECTANGLE TWIDDLED
				masksize = width * height
			else: # VQ
				masksize = 1024

			mask = bs.readBytes(masksize)

			if format & 4:
				pixMapTwiddled = rapi.imageFromMortonOrder(mask,width,height,1,2)
				sourceData = rapi.imageDecodeRaw(pixMapTwiddled, width, height, "r2g2b2p2")
			else:
				maskmap = bytearray(masksize * 2)
				maskmap[0::2] = mask
				maskmap[1::2] = mask
				decompTex = rapi.loadTexByHandler(header + maskmap + indices, ".pvr")
				sourceData = decompTex.pixelData if decompTex else None

			maskTexture = NoeTexture(texname + '_mask', width, height, sourceData, noesis.NOESISTEX_RGBA32)
			self.textures.append(maskTexture)



class MetSUB:
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
	metFile = MetFILE()
	metFile.parse(bs)

	for lod in metFile.lods:
		ctx = rapi.rpgCreateContext()

		for tex in lod.textures:
			noeTextures.append(tex)

		for group in lod.groups:
			if (group.hasName):
				if (group.name in ("ENV", "Highlight_Model")):
					continue
				rapi.rpgSetName(group.name)
			rapi.rpgSetPosScaleBias(None, group.grp_pos)
			for sub in group.subs:
				if group.hasName and group.name in ("HLC","WSM","WS2","Windscreen_Model"):
					rapi.rpgSetMaterial("wnd_normal")
				else:
					rapi.rpgSetMaterial(lod.materials[sub.matId].name)

				rapi.rpgBindPositionBufferOfs(sub.vtxData, noesis.RPGEODATA_FLOAT, stride, 0)
				rapi.rpgBindUV1BufferOfs(sub.vtxData, noesis.RPGEODATA_FLOAT, stride, 16)
				for strip in sub.strips:
					rapi.rpgCommitTriangles( strip[0], noesis.RPGEODATA_USHORT,
					strip[1], noesis.RPGEO_TRIANGLE_STRIP, 1)

				rapi.rpgClearBufferBinds()
		rapi.rpgOptimize()
		mdl = rapi.rpgConstructModel()
		
		wndMat = NoeMaterial("wnd_normal", "glass0")
		wndTex = NoeTexture("glass0", 2, 2, b'\0\0\0\x70' * 4)
		wndMat.setFlags(noesis.NMATFLAG_SORT01)
		wndMat.setDiffuseColor(NoeVec4([1.0,1.0,1.0,100 / 255]))
		lod.materials.append(wndMat)
		lod.textures.append(wndTex)

		mdl.setModelMaterials(NoeModelMaterials(lod.textures, lod.materials))
		mdlList.append(mdl)
	return 1