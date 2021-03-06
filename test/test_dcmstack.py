"""
Tests for dcmstack.dcmstack
"""
import sys, shutil
from os import path
from glob import glob
from hashlib import sha256
from tempfile import mkdtemp
from shutil import rmtree
from nose.tools import ok_, eq_, assert_raises
import numpy as np
import dicom
import nibabel as nb

test_dir = path.dirname(__file__)
src_dir = path.normpath(path.join(test_dir, '../src'))
sys.path.insert(0, src_dir)

import dcmstack

def test_key_regex_filter():
        filt = dcmstack.make_key_regex_filter(['test', 'another'], 
                                              ['2', 'another test'])
        ok_(filt('test', 1))
        ok_(filt('test another', 1))
        ok_(filt('another tes', 1))
        ok_(not filt('test2', 1))
        ok_(not filt('2 another', 1))
        ok_(not filt('another test', 1))
        
def test_closest_ortho_pat_axis():
    eq_(dcmstack.closest_ortho_pat_axis((0.9, 0.1, 0.1)), 'lr')
    eq_(dcmstack.closest_ortho_pat_axis((-0.9, 0.1, 0.1)), 'rl')
    eq_(dcmstack.closest_ortho_pat_axis((0.1, 0.9, 0.1)), 'pa')
    eq_(dcmstack.closest_ortho_pat_axis((0.1, -0.9, 0.1)), 'ap')
    eq_(dcmstack.closest_ortho_pat_axis((0.1, 0.1, 0.9)), 'is')
    eq_(dcmstack.closest_ortho_pat_axis((0.1, 0.1, -0.9)), 'si')
    
class TestReorderVoxels(object):
    def setUp(self):
        self.vox_array = np.arange(16).reshape((2, 2, 2, 2))
        self.affine = np.eye(4)
        
    def test_invalid_vox_order(self):
        assert_raises(ValueError, 
                      dcmstack.reorder_voxels,
                      self.vox_array, 
                      self.affine, 
                      'lra', 
                      )
        assert_raises(ValueError, 
                      dcmstack.reorder_voxels,
                      self.vox_array, 
                      self.affine, 
                      'rpil', 
                      )
        assert_raises(ValueError, 
                      dcmstack.reorder_voxels,
                      self.vox_array, 
                      self.affine, 
                      'lrz', 
                      )
        
    def test_invalid_vox_array(self):
        assert_raises(ValueError,
                      dcmstack.reorder_voxels,
                      np.eye(2), 
                      self.affine, 
                      'rpi', 
                     )
        
    def test_invalid_affine(self):
        assert_raises(ValueError,
                      dcmstack.reorder_voxels,
                      self.vox_array, 
                      np.eye(3), 
                      'rpi', 
                     )
                     
    def test_no_op(self):
        vox_order = [dcmstack.closest_ortho_pat_axis(self.affine[:3, idx])[0] 
                     for idx in range(3)
                    ]
        vox_order = ''.join(vox_order)                             
        vox_array, affine, perm = dcmstack.reorder_voxels(self.vox_array, 
                                                          self.affine, 
                                                          vox_order)
        ok_((vox_array == self.vox_array).all())
        ok_((affine == self.affine).all())
        eq_(perm, (0, 1, 2))
        eq_(np.may_share_memory(affine, self.affine), False)
        
def test_dcm_time_to_sec():
    eq_(dcmstack.dcm_time_to_sec('100235.123456'), 36155.123456)
    
class TestDicomOrdering(object):
    def setUp(self):
        self.ds = {'EchoTime' : 2}
        
    def test_missing_key(self):
        ordering = dcmstack.DicomOrdering('blah')
        eq_(ordering.get_ordinate(self.ds), None)
        
    def test_non_abs(self):
        ordering = dcmstack.DicomOrdering('EchoTime')
        eq_(ordering.get_ordinate(self.ds), self.ds['EchoTime'])
        
    def test_abs(self):
        abs_order = [1,2,3]
        ordering = dcmstack.DicomOrdering('EchoTime', abs_ordering=abs_order)
        eq_(ordering.get_ordinate(self.ds), 
            abs_order.index(self.ds['EchoTime']))
            
    def test_abs_as_str(self):
        abs_order = ['1','2','3']
        ordering = dcmstack.DicomOrdering('EchoTime', 
                                          abs_ordering=abs_order, 
                                          abs_as_str=True)
        eq_(ordering.get_ordinate(self.ds), 
            abs_order.index(str(self.ds['EchoTime'])))
            
    def test_abs_missing(self):
        abs_order = [1,3]
        ordering = dcmstack.DicomOrdering('EchoTime', abs_ordering=abs_order)
        assert_raises(ValueError,
                      ordering.get_ordinate,
                      self.ds
                     )

def test_image_collision():
    dcm_path = path.join(test_dir, 
                         'data', 
                         'dcmstack', 
                         '2D_16Echo_qT2', 
                         'TE_20_SlcPos_-33.707626341697.dcm')
    dcm = dicom.read_file(dcm_path)
    stack = dcmstack.DicomStack()
    stack.add_dcm(dcm)
    assert_raises(dcmstack.ImageCollisionError,
                  stack.add_dcm,
                  dcm)
    
def TestIncongruentImage():
    def setUp(self):
        dcm_path = path.join(test_dir, 
                             'data', 
                             'dcmstack', 
                             '2D_16Echo_qT2', 
                             'TE_20_SlcPos_-33.707626341697.dcm')
        self.dcm = dicom.read_file(dcm_path)
    
        self.stack = dcmstack.DicomStack()
        self.stack.add_dcm(dcm)
        
    def _chk(self):
        assert_raises(dcmstack.IncongruentImageError,
                      self.stack.add_dcm,
                      self.dcm)
    
    def test_rows(self):
        self.dcm.Rows += 1
        self._chk()
    
    def test_columns(self):
        dcm.Columns += 1
        self._chk()
    
    def test_pix_space(self):
        dcm.PixelSpacing[0] * 2
        self._chk()
        
    def test_orientation(self):
        dcm.ImageOrientationPatient = [0.5 * elem 
                                       for elem in dcm.ImageOrientationPatient
                                      ]
        self._chk()
        

class TestInvalidStack(object):
    def setUp(self):
        data_dir = path.join(test_dir, 
                             'data', 
                             'dcmstack', 
                             '2D_16Echo_qT2')
        self.inputs = [dicom.read_file(path.join(data_dir, fn)) 
                       for fn in ('TE_20_SlcPos_-33.707626341697.dcm',
                                  'TE_20_SlcPos_-23.207628249046.dcm',
                                  'TE_40_SlcPos_-33.707626341697.dcm',
                                  'TE_60_SlcPos_-23.207628249046.dcm',
                                  'TE_20_SlcPos_-2.2076272953718.dcm'
                                  )
                      ]
    
    def _chk(self):
        assert_raises(dcmstack.InvalidStackError,
                      self.stack.get_shape)
        assert_raises(dcmstack.InvalidStackError,
                      self.stack.get_affine)
        assert_raises(dcmstack.InvalidStackError,
                      self.stack.get_data)
        assert_raises(dcmstack.InvalidStackError,
                      self.stack.to_nifti)
    
    def test_empty(self):
        self.stack = dcmstack.DicomStack()
        self._chk()
        
    def test_only_dummy(self):
        self.stack = dcmstack.DicomStack(allow_dummies=True)
        del self.inputs[0].Rows
        del self.inputs[0].Columns
        del self.inputs[1].Rows
        del self.inputs[1].Columns
        self.stack.add_dcm(self.inputs[0])
        self.stack.add_dcm(self.inputs[1])
        self._chk()
        
    def test_missing_slice(self):
        self.stack = dcmstack.DicomStack()
        self.stack.add_dcm(self.inputs[0])
        self.stack.add_dcm(self.inputs[1])
        self.stack.add_dcm(self.inputs[4])
        self._chk()
        
    def test_wrong_number_of_files(self):
        self.stack = dcmstack.DicomStack(time_order='EchoTime')
        self.stack.add_dcm(self.inputs[0])
        self.stack.add_dcm(self.inputs[1])
        self.stack.add_dcm(self.inputs[2])
        self._chk()
        
    def test_vector_var_over_vol(self):
        self.stack = dcmstack.DicomStack(vector_order='EchoTime')
        self.stack.add_dcm(self.inputs[0])
        self.stack.add_dcm(self.inputs[1])
        self.stack.add_dcm(self.inputs[2])
        self.stack.add_dcm(self.inputs[3])
        self._chk()
                                
class TestGetShape(object):
    def setUp(self):
        data_dir = path.join(test_dir, 
                             'data', 
                             'dcmstack', 
                             '2D_16Echo_qT2')
        self.inputs = [dicom.read_file(path.join(data_dir, fn)) 
                       for fn in ('TE_40_SlcPos_-33.707626341697.dcm',
                                  'TE_40_SlcPos_-23.207628249046.dcm',
                                  'TE_60_SlcPos_-33.707626341697.dcm',
                                  'TE_60_SlcPos_-23.207628249046.dcm',
                                  )
                      ]
        
    def test_single_slice(self):
        stack = dcmstack.DicomStack()
        stack.add_dcm(self.inputs[0])
        shape = stack.get_shape()
        eq_(shape, (192, 192, 1))
        
    def test_three_dim(self):
        stack = dcmstack.DicomStack()
        stack.add_dcm(self.inputs[0])
        stack.add_dcm(self.inputs[1])
        shape = stack.get_shape()
        eq_(shape, (192, 192, 2))
        
    def test_four_dim(self):
        stack = dcmstack.DicomStack(time_order='EchoTime')
        stack.add_dcm(self.inputs[0])
        stack.add_dcm(self.inputs[1])
        stack.add_dcm(self.inputs[2])
        stack.add_dcm(self.inputs[3])
        shape = stack.get_shape()
        eq_(shape, (192, 192, 2, 2))
        
    def test_five_dim(self):
        stack = dcmstack.DicomStack(vector_order='EchoTime')
        stack.add_dcm(self.inputs[0])
        stack.add_dcm(self.inputs[1])
        stack.add_dcm(self.inputs[2])
        stack.add_dcm(self.inputs[3])
        shape = stack.get_shape()
        eq_(shape, (192, 192, 2, 1, 2))
        
    def test_allow_dummy(self):
        del self.inputs[0].Rows
        del self.inputs[0].Columns
        stack = dcmstack.DicomStack(allow_dummies=True)
        stack.add_dcm(self.inputs[0])
        stack.add_dcm(self.inputs[1])
        shape = stack.get_shape()
        eq_(shape, (192, 192, 2))
        
class TestGetData(object):
    def setUp(self):
        data_dir = path.join(test_dir, 
                             'data', 
                             'dcmstack', 
                             '2D_16Echo_qT2')
        self.inputs = [dicom.read_file(path.join(data_dir, fn)) 
                       for fn in ('TE_40_SlcPos_-33.707626341697.dcm',
                                  'TE_40_SlcPos_-23.207628249046.dcm',
                                  'TE_60_SlcPos_-33.707626341697.dcm',
                                  'TE_60_SlcPos_-23.207628249046.dcm',
                                  )
                      ]
        
    def test_single_slice(self):
        stack = dcmstack.DicomStack()
        stack.add_dcm(self.inputs[0])
        data = stack.get_data()
        eq_(data.shape, stack.get_shape())
        eq_(sha256(data).hexdigest(),
            '15cfa107ca73810a1c97f1c1872a7a4a05808ba6147e039cef3f63fa08735f5d')
        
    def test_three_dim(self):
        stack = dcmstack.DicomStack()
        stack.add_dcm(self.inputs[0])
        stack.add_dcm(self.inputs[1])
        data = stack.get_data()
        eq_(data.shape, stack.get_shape())
        eq_(sha256(data).hexdigest(),
            'ec60d148734916bb05aa7d73cc76bd0777560518da86d1ac5aa93c8f151cf73f')
            
    def test_four_dim(self):
        stack = dcmstack.DicomStack(time_order='EchoTime')
        stack.add_dcm(self.inputs[0])
        stack.add_dcm(self.inputs[1])
        stack.add_dcm(self.inputs[2])
        stack.add_dcm(self.inputs[3])
        data = stack.get_data()
        eq_(data.shape, stack.get_shape())
        eq_(sha256(data).hexdigest(),
            'c14d3a8324bdf4b85be05d765c0864b4e2661d7aa716adaf85a28b4102e1992b')
            
    def test_five_dim(self):
        stack = dcmstack.DicomStack(vector_order='EchoTime')
        stack.add_dcm(self.inputs[0])
        stack.add_dcm(self.inputs[1])
        stack.add_dcm(self.inputs[2])
        stack.add_dcm(self.inputs[3])
        data = stack.get_data()
        eq_(data.shape, stack.get_shape())
        eq_(sha256(data).hexdigest(),
            'c14d3a8324bdf4b85be05d765c0864b4e2661d7aa716adaf85a28b4102e1992b')
            
    def test_allow_dummy(self):
        del self.inputs[0].Rows
        del self.inputs[0].Columns
        stack = dcmstack.DicomStack(allow_dummies=True)
        stack.add_dcm(self.inputs[0])
        stack.add_dcm(self.inputs[1])
        data = stack.get_data()
        eq_(data.shape, stack.get_shape())
        eq_(sha256(data).hexdigest(),
            '4daeb630fce867f96a1dad7962fa74e902e7710d6cd65408bd2164c0278a9671')
            
class TestGetAffine(object):
    def setUp(self):
        self.data_dir = path.join(test_dir, 
                             'data', 
                             'dcmstack', 
                             '2D_16Echo_qT2')
        self.inputs = [dicom.read_file(path.join(self.data_dir, fn)) 
                       for fn in ('TE_20_SlcPos_-33.707626341697.dcm',
                                  'TE_20_SlcPos_-23.207628249046.dcm'
                                 )
                      ]
                      
    def test_single_slice(self):
        stack = dcmstack.DicomStack()
        stack.add_dcm(self.inputs[0])
        affine = stack.get_affine()
        ref = np.load(path.join(self.data_dir, 'single_slice_aff.npy'))
        ok_(np.all(affine == ref))
    
    def test_three_dim(self):
        stack = dcmstack.DicomStack()
        stack.add_dcm(self.inputs[0])
        stack.add_dcm(self.inputs[1])
        affine = stack.get_affine()
        ref = np.load(path.join(self.data_dir, 'single_vol_aff.npy'))
        ok_(np.all(affine == ref))
    
class TestToNifti(object):
    def setUp(self):
        self.data_dir = path.join(test_dir, 
                             'data', 
                             'dcmstack', 
                             '2D_16Echo_qT2')
        self.inputs = [dicom.read_file(path.join(self.data_dir, fn)) 
                       for fn in ('TE_20_SlcPos_-33.707626341697.dcm',
                                  'TE_20_SlcPos_-23.207628249046.dcm',
                                  'TE_40_SlcPos_-33.707626341697.dcm',
                                  'TE_40_SlcPos_-23.207628249046.dcm',
                                 )
                      ]
        self.tmp_dir = mkdtemp(prefix='dcmstack_test')
        
    def tearDown(self):
        rmtree(self.tmp_dir)
        
    def _chk(self, ref_base_fn, embed):
        nii = self.stack.to_nifti(embed_meta=embed)
        nii_path = path.join(self.tmp_dir, 'test.nii')
        nb.save(nii, nii_path)
        
        test_fd = open(nii_path)
        test_data = test_fd.read()
        test_fd.close()
        test_sha = sha256(test_data).hexdigest()
        
        ref_fn = ref_base_fn
        if embed:
            ref_fn += '_embed'
        else:
            ref_fn += '_non_embed'
        ref_fn += '.sha256sum'
        ref_fd = open(path.join(self.data_dir, ref_fn))
        ref_sha = ref_fd.read().strip()
        ref_fd.close()
        eq_(test_sha, ref_sha)
        
    def test_single_slice(self, embed=False):
        self.stack = dcmstack.DicomStack()
        self.stack.add_dcm(self.inputs[0])
        self._chk('single_slice', embed)
        
    def test_single_slice_embed(self):
        self.test_single_slice(True)
        
    def test_single_vol(self, embed=False):
        self.stack = dcmstack.DicomStack()
        self.stack.add_dcm(self.inputs[0])
        self.stack.add_dcm(self.inputs[1])
        self._chk('single_vol', embed)
        
    def test_single_vol_embed(self):
        self.test_single_vol(True)
        
    def test_two_time_vol(self, embed=False):
        self.stack = dcmstack.DicomStack(time_order='EchoTime')
        self.stack.add_dcm(self.inputs[0])
        self.stack.add_dcm(self.inputs[1])
        self.stack.add_dcm(self.inputs[2])
        self.stack.add_dcm(self.inputs[3])
        self._chk('two_time_vol', embed)
        
    def test_two_time_vol_embed(self):
        self.test_two_time_vol(True)
        
    def test_two_vector_vol(self, embed=False):
        self.stack = dcmstack.DicomStack(vector_order='EchoTime')
        self.stack.add_dcm(self.inputs[0])
        self.stack.add_dcm(self.inputs[1])
        self.stack.add_dcm(self.inputs[2])
        self.stack.add_dcm(self.inputs[3])
        self._chk('two_vector_vol', embed)
        
    def test_two_vector_vol_embed(self):
        self.test_two_vector_vol(True)
        