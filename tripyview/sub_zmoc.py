# Patrick, Scholz 02.09.2018
import numpy as np
import time as clock
import os
from netCDF4 import Dataset
import xarray as xr
import matplotlib
matplotlib.rcParams['contour.negative_linestyle']= 'solid'
import matplotlib.pyplot as plt
#import matplotlib.patches as Polygon
#import matplotlib.path as mpltPath
#from matplotlib.tri import Triangulation
from numba import jit, njit, prange
import shapefile as shp
from matplotlib.ticker import FormatStrFormatter
from scipy.interpolate import interp1d
from numpy.matlib import repmat
from scipy import interpolate
import numpy.ma as ma

from .sub_colormap import *
from .sub_utility  import *
from .sub_plot     import *

#+___CALCULATE MERIDIONAL OVERTURNING FROM VERTICAL VELOCITIES_________________+
#| Global MOC, Atlantik MOC, Indo-Pacific MOC, Indo MOC                        |
#|                                                                             |
#| which_moc=:                                                                 |
#| 'gmoc'  ... compute global MOC                                              |
#| 'amoc'  ... compute MOC for Atlantic Basin                                  |
#| 'aamoc' ... compute MOC for Atlantic+Artic Basin                            |
#| 'pmoc'  ... compute MOC for Pacific Basin                                   |
#| 'ipmoc' ... compute MOC for Indo-Pacific Basin (PMOC how it should be)      |
#| 'imoc'  ... compute MOC for Indian-Ocean Basin                              |
#|                                                                             |
#| Important:                                                                  |
#| Between 'amoc' and 'aamoc' there is not much difference in variability, but |
#| upto 1.5Sv in amplitude. Where 'aamoc' is stronger than 'amoc'. There is no |
#| clear rule which one is better, just be sure you are consistent             |
#+_____________________________________________________________________________+
def calc_zmoc(mesh, data, dlat=1.0, which_moc='gmoc', do_onelem=False, 
              do_info=True, diagpath=None,  do_compute=False, do_checkbasin=False, 
              **kwargs,
             ):
    #_________________________________________________________________________________________________
    t1=clock.time()
    if do_info==True: print('_____calc. '+which_moc.upper()+' from vertical velocities via meridional bins_____')
        
    #___________________________________________________________________________
    # calculate/use index for basin domain limitation
    idxin = calc_basindomain_fast(mesh, which_moc=which_moc, do_onelem=do_onelem)
    
    #___________________________________________________________________________
    if do_checkbasin:
        from matplotlib.tri import Triangulation
        tri = Triangulation(np.hstack((mesh.n_x,mesh.n_xa)), np.hstack((mesh.n_y,mesh.n_ya)), np.vstack((mesh.e_i[mesh.e_pbnd_0,:],mesh.e_ia)))
        plt.figure()
        plt.triplot(tri, color='k')
        if do_onelem:
            plt.triplot(tri.x, tri.y, tri.triangles[ np.hstack((idxin[mesh.e_pbnd_0], idxin[mesh.e_pbnd_a])) ,:], color='r')
        else:
            plt.plot(mesh.n_x[idxin], mesh.n_y[idxin], 'or', linestyle='None', markersize=1)
        plt.title('Basin selection')
        plt.show()
    
    #___________________________________________________________________________
    # rescue global attributes
    gattr = data.attrs
    
    #___________________________________________________________________________
    # do moc calculation either on nodes or on elements        
    # keep in mind that node area info is changing over depth--> therefor load from file 
    if diagpath is None:
        fname = data['w'].attrs['runid']+'.mesh.diag.nc'
        
        if   os.path.isfile( os.path.join(data['w'].attrs['datapath'], fname) ): 
            dname = data['w'].attrs['datapath']
        elif os.path.isfile( os.path.join( os.path.join(os.path.dirname(os.path.normpath(data['w'].attrs['datapath'])),'1/'), fname) ): 
            dname = os.path.join(os.path.dirname(os.path.normpath(data['w'].attrs['datapath'])),'1/')
        elif os.path.isfile( os.path.join(mesh.path,fname) ): 
            dname = mesh.path
        else:
            raise ValueError('could not find directory with...mesh.diag.nc file')
        
        diagpath = os.path.join(dname,fname)
        if do_info: print(' --> found diag in directory:{}', diagpath)
        
    #___________________________________________________________________________
    # compute area weighted vertical velocities on elements
    if do_onelem:
        #_______________________________________________________________________
        edims = dict()
        dtime, delem, dnz = 'None', 'elem', 'nz'
        if 'time' in list(data.dims): dtime = 'time'
        
        #_______________________________________________________________________
        # load elem area from diag file
        if ( os.path.isfile(diagpath)):
            nz_w_A = xr.open_mfdataset(diagpath, parallel=True, **kwargs)['elem_area']#.chunk({'elem':1e4})
            if 'elem_n' in list(nz_w_A.dims): nz_w_A = nz_w_A.rename({'elem_n':'elem'})
            if 'nl'     in list(nz_w_A.dims): nz_w_A = nz_w_A.rename({'nl'    :'nz'  })
            if 'nl1'    in list(nz_w_A.dims): nz_w_A = nz_w_A.rename({'nl1'   :'nz1' }) 
            nz_w_A = nz_w_A.isel(elem=idxin)
        else: 
            raise ValueError('could not find ...mesh.diag.nc file')
        
        #_______________________________________________________________________    
        # average from vertices towards elements
        e_i = xr.DataArray(mesh.e_i, dims=["elem",'n3'])
        if 'time' in list(data.dims): 
            data = data.assign(w=data['w'][:, e_i, :].sum(dim="n3", keep_attrs=True)/3.0 )
        else:  
            data = data.assign(w=data['w'][   e_i, :].sum(dim="n3", keep_attrs=True)/3.0 )
        data = data.drop(['lon', 'lat', 'nodi', 'nodiz', 'w_A'])    
        data = data.assign_coords(elemiz= xr.DataArray(mesh.e_iz, dims=['elem']))
        data = data.assign_coords(elemi = xr.DataArray(np.arange(0,mesh.n2de), dims=['elem']))
        
        #_______________________________________________________________________    
        # select MOC basin 
        data = data.isel(elem=idxin)
        
        #_______________________________________________________________________    
        # enforce bottom topography --> !!! important otherwise results will look 
        # weired
        mat_elemiz = data['elemiz'].expand_dims({'nz': data['nzi']}).transpose()
        mat_nzielem= data['nzi'].expand_dims({'elemi': data['elemi']})
        data = data.where(mat_nzielem.data<mat_elemiz.data)
        del(mat_elemiz, mat_nzielem)
        
        #_______________________________________________________________________
        # calculate area weighted mean
        data = data.transpose(dtime, dnz, delem, missing_dims='ignore') * nz_w_A * 1e-6
        data = data.transpose(dtime, delem, dnz, missing_dims='ignore')
        data = data.fillna(0.0)
        del(nz_w_A)
        
        #_______________________________________________________________________
        # create meridional bins --> this trick is from Nils Brückemann (ICON)
        lat     = mesh.n_y[mesh.e_i].sum(axis=1)/3.0
        lat_bin = xr.DataArray(data=np.round(lat[idxin]/dlat)*dlat, dims='elem', name='lat')  
    
    #___________________________________________________________________________
    # compute area weighted vertical velocities on vertices
    else:    
        #_______________________________________________________________________
        # load vertice cluster area from diag file
        if ( os.path.isfile(diagpath)):
            nz_w_A = xr.open_mfdataset(diagpath, parallel=True, **kwargs)['nod_area']#.chunk({'nod2':1e4})
            if 'nod_n' in list(nz_w_A.dims): nz_w_A = nz_w_A.rename({'nod_n':'nod2'})
            if 'nl'    in list(nz_w_A.dims): mat_area = nz_w_A.rename({'nl'   :'nz'  })
            if 'nl1'   in list(nz_w_A.dims): nz_w_A = nz_w_A.rename({'nl1'  :'nz1' })
            # you need to drop here the coordinates for nz since they go from 
            # 0...-6000 the coordinates of nz in the data go from 0...6000 that 
            # causes otherwise troubles
            nz_w_A = nz_w_A.isel(nod2=idxin).drop(['nz'])
            
        else: 
            raise ValueError('could not find ...mesh.diag.nc file')
        
        #_______________________________________________________________________    
        # select MOC basin 
        data = data.isel(nod2=idxin)
        
        #_______________________________________________________________________
        # calculate area weighted mean
        data = data * nz_w_A * 1e-6
        data = data.fillna(0.0)
        del(nz_w_A)
        
        #_______________________________________________________________________
        # create meridional bins --> this trick is from Nils Brückemann (ICON)
        lat_bin = xr.DataArray(data=np.round(data.lat/dlat)*dlat, dims='nod2', name='lat')    
        
    #___________________________________________________________________________
    # group data by bins --> this trick is from Nils Brückemann (ICON)
    if do_info==True: print(' --> do binning of latitudes')
    data    = data.rename_vars({'w':'zmoc', 'nz':'depth'})
    data    = data.groupby(lat_bin)
    
    # zonal sumation/integration over bins
    if do_info==True: print(' --> do sumation/integration over bins')
    data    = data.sum(skipna=True)
    
    # transpose data from [lat x nz] --> [nz x lat]
    dtime, dlat, dnz = 'None', 'lat', 'nz'
    if 'time' in list(data.dims): dtime = 'time'
    data = data.transpose(dtime, dnz, dlat, missing_dims='ignore')
    
    #___________________________________________________________________________
    # cumulative sum over latitudes
    if do_info==True: print(' --> do cumsum over latitudes')
    data['zmoc'] = -data['zmoc'].reindex(lat=data['lat'][::-1]).cumsum(dim='lat', skipna=True).reindex(lat=data['lat'])
    
    #___________________________________________________________________________
    # write proper global and local variable attributes for long_name and units 
    data    = data.assign_attrs(gattr) # put back global attributes
    attr_list = dict({'long_name':'MOC', 'units':'Sv'})
    data['zmoc'] = data['zmoc'].assign_attrs(attr_list)
    
    #___________________________________________________________________________
    # compute depth of max and nice bottom topography
    if do_onelem: data = calc_bottom_patch(data, lat_bin, xr.DataArray(mesh.e_iz, dims=['elem']), idxin)        
    else        : data = calc_bottom_patch(data, lat_bin, xr.DataArray(mesh.n_iz, dims=['nod2']), idxin)
    
    #___________________________________________________________________________
    # write some infos 
    t2=clock.time()
    if do_info==True: 
        print(' --> total time:{:.3f} s'.format(t2-t1))
        if 'time' not in list(data.dims):
            if which_moc in ['amoc', 'aamoc', 'gmoc']:
                maxv = data.isel(nz=data['depth']>= 700 , lat=data['lat']>0.0)['zmoc'].max().values
                minv = data.isel(nz=data['depth']>= 2500, lat=data['lat']>-50.0)['zmoc'].min().values
                print(' max. NADW_{:s} = {:.2f} Sv'.format(data['zmoc'].attrs['descript'],maxv))
                print(' max. AABW_{:s} = {:.2f} Sv'.format(data['zmoc'].attrs['descript'],minv))
            elif which_moc in ['pmoc', 'ipmoc']:
                minv = data['zmoc'].isel(nz=data['depth']>= 2000, lat=data['lat']>-50.0)['moc'].min().values
                print(' max. AABW_{:s} = {:.2f} Sv'.format(data['zmoc'].attrs['descript'],minv))
    
    #___________________________________________________________________________
    if do_compute: data = data.compute()
    
    #___________________________________________________________________________
    return(data)


#+___CALC BOTTOM TOPO PATCH____________________________________________________+
#|                                                                             |
#+_____________________________________________________________________________+
def calc_bottom_patch(data, lat_bin, idx_iz, idxin):
    idx_z = data['depth'][idx_iz]
    idx_z = idx_z.isel({ list(idx_z.dims)[0] : idxin})
    idx_z = idx_z.groupby(lat_bin)
    #___________________________________________________________________________
    # maximum bottom topography for MOC
    botmax= idx_z.max()
    data  = data.assign_coords(botmax = botmax)
    
    #___________________________________________________________________________
    # optiocal nicer bottom topography for MOC
    botnic= idx_z.quantile(1-0.20, skipna=True).drop(['quantile'])
    
    # smooth bottom topography patch
    #filt=np.array([1,2,3,2,1])
    filt=np.array([1,2,1])
    filt=filt/np.sum(filt)
    aux = np.concatenate( (np.ones((filt.size,))*botnic.data[0],botnic.data,np.ones((filt.size,))*botnic.data[-1] ) )
    aux = np.convolve(aux,filt,mode='same')
    botnic.data = aux[filt.size:-filt.size]
    del(aux)
    
    data  = data.assign_coords(botnice= botnic)
    
    #___________________________________________________________________________
    # index for max bottom index for every lat bin 
    #idx_iz    = idx_iz.isel({list(idx_z.dims)[0] : idxin})
    #idx_iz    = nodeiz.groupby(lat_bin).max()
    #data      = data.assign_coords(botmaxi=idx_iz)
    
    #___________________________________________________________________________
    return(data)


#+___PLOT MERIDIONAL OVERTRUNING CIRCULATION  _________________________________+
#|                                                                             |
#+_____________________________________________________________________________+
def plot_zmoc(data, which_moc='gmoc', figsize=[12, 6], 
              n_rc=[1, 1], do_grid=True, cinfo=None, do_rescale=None, 
              do_reffig=False, ref_cinfo=None, ref_rescale=None,
              cbar_nl=8, cbar_orient='vertical', cbar_label=None, cbar_unit=None,
              do_bottom=True, color_bot=[0.6, 0.6, 0.6], 
              pos_fac=1.0, pos_gap=[0.01, 0.01], do_save=None, save_dpi=600, 
              do_contour=True, do_clabel=True, title='descript', 
              pos_extend=[0.075, 0.075, 0.90, 0.95] ):
    #____________________________________________________________________________
    fontsize = 12
    
    #___________________________________________________________________________
    # make matrix with row colum index to know where to put labels
    rowlist = np.zeros((n_rc[0], n_rc[1]))
    collist = np.zeros((n_rc[0], n_rc[1]))       
    for ii in range(0,n_rc[0]): rowlist[ii,:]=ii
    for ii in range(0,n_rc[1]): collist[:,ii]=ii
    rowlist = rowlist.flatten()
    collist = collist.flatten()
    
    #___________________________________________________________________________    
    # create figure and axes
    fig, ax = plt.subplots( n_rc[0],n_rc[1],
                                figsize=figsize, 
                                gridspec_kw=dict(left=0.1, bottom=0.1, right=0.9, top=0.9, wspace=0.05, hspace=0.05,),
                                constrained_layout=False, sharex=True, sharey=True)
    
    #___________________________________________________________________________    
    # flatt axes if there are more than 1
    if isinstance(ax, np.ndarray): ax = ax.flatten()
    else:                          ax = [ax] 
    nax = len(ax)
     
    #___________________________________________________________________________
    # data must be list filled with xarray data
    if not isinstance(data  , list): data  = [data]
    ndata = len(data) 
    
    #___________________________________________________________________________
    # set up color info 
    if do_reffig:
        ref_cinfo = do_setupcinfo(ref_cinfo, [data[0]], ref_rescale, do_moc=True)
        cinfo     = do_setupcinfo(cinfo    , data[1:] , do_rescale , do_moc=True)
    else:
        cinfo     = do_setupcinfo(cinfo    , data     , do_rescale , do_moc=True)
        
    #___________________________________________________________________________
    # loop over axes
    ndi, nli, nbi =0, 0, 0
    hpall=list()
    for ii in range(0,ndata):
        
        #_______________________________________________________________________
        # limit data to color range
        data_plot = data[ii]['zmoc'].values
        lat       = data[ii]['lat'].values
        depth     = data[ii]['depth'].values
        
        #_______________________________________________________________________
        if do_reffig: 
            if ii==0: cinfo_plot = ref_cinfo
            else    : cinfo_plot = cinfo
        else: cinfo_plot = cinfo
        
        #_______________________________________________________________________
        data_plot[data_plot<cinfo_plot['clevel'][ 0]] = cinfo_plot['clevel'][ 0]+np.finfo(np.float32).eps
        data_plot[data_plot>cinfo_plot['clevel'][-1]] = cinfo_plot['clevel'][-1]-np.finfo(np.float32).eps
        
        #_______________________________________________________________________
        # plot MOC
        hp=ax[ii].contourf(lat, depth, data_plot, 
                           levels=cinfo_plot['clevel'], extend='both', cmap=cinfo_plot['cmap'])
        hpall.append(hp)
        
        if do_contour: 
            tickl    = cinfo_plot['clevel']
            ncbar_l  = len(tickl)
            idx_cref = np.where(cinfo_plot['clevel']==cinfo_plot['cref'])[0]
            idx_cref = np.asscalar(idx_cref)
            nstep    = ncbar_l/cbar_nl
            nstep    = np.max([np.int(np.floor(nstep)),1])
            
            idx = np.arange(0, ncbar_l, 1)
            idxb = np.ones((ncbar_l,), dtype=bool)                
            idxb[idx_cref::nstep]  = False
            idxb[idx_cref::-nstep] = False
            idx_yes = idx[idxb==False]
            
            cont=ax[ii].contour(lat, depth, data_plot, 
                            levels=cinfo_plot['clevel'][idx_yes], colors='k', linewidths=[0.5]) #linewidths=[0.5,0.25])
            if do_clabel: 
                ax[ii].clabel(cont, cont.levels[np.where(cont.levels!=cinfo_plot['cref'])], 
                            inline=1, inline_spacing=1, fontsize=6, fmt='%1.1f Sv')
            ax[ii].contour(lat, depth, data_plot, 
                            levels=[0.0], colors='k', linewidths=[1.25]) #linewidths=[0.5,0.25])
            
        if do_bottom:
            #bottom    = data[ii]['botmax'].values
            bottom    = data[ii]['botnice'].values
            ax[ii].plot(lat, bottom, color='k')
            ax[ii].fill_between(lat, bottom, depth[-1], color=color_bot, zorder=2)#,alpha=0.95)
        
        #_______________________________________________________________________
        # fix color range
        for im in ax[ii].get_images(): im.set_clim(cinfo_plot['clevel'][ 0], cinfo_plot['clevel'][-1])
        
        #_______________________________________________________________________
        # plot grid lines 
        if do_grid: ax[ii].grid(color='k', linestyle='-', linewidth=0.25,alpha=1.0)
        
        #_______________________________________________________________________
        # set description string plus x/y labels
        if title is not None: 
            txtx, txty = lat[0]+(lat[-1]-lat[0])*0.025, depth[-1]-(depth[-1]-depth[0])*0.025                    
            if   isinstance(title,str) : 
                # if title string is 'descript' than use descript attribute from 
                # data to set plot title 
                if title=='descript' and ('descript' in data[ii]['zmoc'].attrs.keys() ):
                    txts = data[ii]['zmoc'].attrs['descript']
                else:
                    txts = title
            # is title list of string        
            elif isinstance(title,list):   
                txts = title[ii]
            ax[ii].text(txtx, txty, txts, fontsize=12, fontweight='bold', horizontalalignment='left')
        
        if collist[ii]==0        : ax[ii].set_ylabel('Depth [m]',fontsize=12)
        if rowlist[ii]==n_rc[0]-1: ax[ii].set_xlabel('Latitudes [deg]',fontsize=12)
        
    nax_fin = ii+1
    
    #___________________________________________________________________________
    # delete axes that are not needed
    #for jj in range(nax_fin, nax): fig.delaxes(ax[jj])
    for jj in range(ndata, nax): fig.delaxes(ax[jj])
    if nax != nax_fin-1: ax = ax[0:nax_fin]
    
    #_______________________________________________________________________
    # invert y axis
    ax[-1].invert_yaxis()
        
    #___________________________________________________________________________
    # delete axes that are not needed
    if do_reffig==False:
        cbar = fig.colorbar(hp, orientation=cbar_orient, ax=ax, ticks=cinfo['clevel'], 
                        extendrect=False, extendfrac=None,
                        drawedges=True, pad=0.025, shrink=1.0)
        
        # do formatting of colorbar 
        cbar = do_cbar_formatting(cbar, do_rescale, cbar_nl, fontsize, cinfo['clevel'])
        
        # do labeling of colorbar
        #if n_rc[0]==1:
            #if   which_moc=='gmoc' : cbar_label = 'Global Meridional \n Overturning Circulation [Sv]'
            #elif which_moc=='amoc' : cbar_label = 'Atlantic Meridional \n Overturning Circulation [Sv]'
            #elif which_moc=='aamoc': cbar_label = 'Arctic-Atlantic Meridional \n Overturning Circulation [Sv]'
            #elif which_moc=='pmoc' : cbar_label = 'Pacific Meridional \n Overturning Circulation [Sv]'
            #elif which_moc=='ipmoc': cbar_label = 'Indo-Pacific Meridional \n Overturning Circulation [Sv]'
            #elif which_moc=='imoc' : cbar_label = 'Indo Meridional \n Overturning Circulation [Sv]'
        #else:    
            #if   which_moc=='gmoc' : cbar_label = 'Global Meridional Overturning Circulation [Sv]'
            #elif which_moc=='amoc' : cbar_label = 'Atlantic Meridional Overturning Circulation [Sv]'
            #elif which_moc=='aamoc': cbar_label = 'Arctic-Atlantic Meridional Overturning Circulation [Sv]'
            #elif which_moc=='pmoc' : cbar_label = 'Pacific Meridional Overturning Circulation [Sv]'
            #elif which_moc=='ipmoc': cbar_label = 'Indo-Pacific Meridional Overturning Circulation [Sv]'
            #elif which_moc=='imoc' : cbar_label = 'Indo Meridional Overturning Circulation [Sv]'
        if   which_moc=='gmoc' : cbar_label = 'Global MOC [Sv]'
        elif which_moc=='amoc' : cbar_label = 'Atlantic MOC [Sv]'
        elif which_moc=='aamoc': cbar_label = 'Arctic-Atlantic MOC [Sv]'
        elif which_moc=='pmoc' : cbar_label = 'Pacific MOC [Sv]'
        elif which_moc=='ipmoc': cbar_label = 'Indo-Pacific MOC [Sv]'
        elif which_moc=='imoc' : cbar_label = 'Indo MOC [Sv]'    
        if 'str_ltim' in data[0]['zmoc'].attrs.keys():
            cbar_label = cbar_label+'\n'+data[0]['zmoc'].attrs['str_ltim']
        cbar.set_label(cbar_label, size=fontsize+2)
        
    else:    
        cbar=list()
        for ii, aux_ax in enumerate(ax): 
            cbar_label = ''
            if ii==0:
                aux_cbar = fig.colorbar(hpall[ii], orientation=cbar_orient, ax=aux_ax, ticks=ref_cinfo['clevel'], 
                                        extendrect=False, extendfrac=None, drawedges=True, pad=0.025, shrink=1.0)
                aux_cbar = do_cbar_formatting(aux_cbar, ref_rescale, cbar_nl, fontsize, ref_cinfo['clevel'])
            else:
                aux_cbar = fig.colorbar(hpall[ii], orientation=cbar_orient, ax=aux_ax, ticks=cinfo['clevel'], 
                                        extendrect=False, extendfrac=None, drawedges=True, pad=0.025, shrink=1.0)
                aux_cbar = do_cbar_formatting(aux_cbar, do_rescale, cbar_nl, fontsize, cinfo['clevel'])
                #cbar_label = 'anomalous '
                cbar_label = 'anom. '
            # do labeling of colorbar
            #if n_rc[0]==1:
                #if   which_moc=='gmoc' : cbar_label = 'Global Meridional \n Overturning Circulation [Sv]'
                #elif which_moc=='amoc' : cbar_label = 'Atlantic Meridional \n Overturning Circulation [Sv]'
                #elif which_moc=='aamoc': cbar_label = 'Arctic-Atlantic Meridional \n Overturning Circulation [Sv]'
                #elif which_moc=='pmoc' : cbar_label = 'Pacific Meridional \n Overturning Circulation [Sv]'
                #elif which_moc=='ipmoc': cbar_label = 'Indo-Pacific Meridional \n Overturning Circulation [Sv]'
                #elif which_moc=='imoc' : cbar_label = 'Indo Meridional \n Overturning Circulation [Sv]'
            #else:    
                #if   which_moc=='gmoc' : cbar_label = 'Global Meridional Overturning Circulation [Sv]'
                #elif which_moc=='amoc' : cbar_label = 'Atlantic Meridional Overturning Circulation [Sv]'
                #elif which_moc=='aamoc': cbar_label = 'Arctic-Atlantic Meridional Overturning Circulation [Sv]'
                #elif which_moc=='pmoc' : cbar_label = 'Pacific Meridional Overturning Circulation [Sv]'
                #elif which_moc=='ipmoc': cbar_label = 'Indo-Pacific Meridional Overturning Circulation [Sv]'
                #elif which_moc=='imoc' : cbar_label = 'Indo Meridional Overturning Circulation [Sv]'
            if   which_moc=='gmoc' : cbar_label = cbar_label+'Global MOC [Sv]'
            elif which_moc=='amoc' : cbar_label = cbar_label+'Atlantic MOC [Sv]'
            elif which_moc=='aamoc': cbar_label = cbar_label+'Arctic-Atlantic MOC [Sv]'
            elif which_moc=='pmoc' : cbar_label = cbar_label+'Pacific MOC [Sv]'
            elif which_moc=='ipmoc': cbar_label = cbar_label+'Indo-Pacific MOC [Sv]'
            elif which_moc=='imoc' : cbar_label = cbar_label+'Indo MOC [Sv]'    
            if 'str_ltim' in data[0]['zmoc'].attrs.keys():
                cbar_label = cbar_label+'\n'+data[0]['zmoc'].attrs['str_ltim']
                #cbar_label = cbar_label+', '+data[0]['moc'].attrs['str_ltim']
            aux_cbar.set_label(cbar_label, size=fontsize+2)
            cbar.append(aux_cbar)
    
    #___________________________________________________________________________
    # repositioning of axes and colorbar
    if do_reffig==False:
        ax, cbar = do_reposition_ax_cbar(ax, cbar, rowlist, collist, pos_fac, pos_gap, 
                                     title=None, extend=pos_extend)
    fig.canvas.draw()
    
    #___________________________________________________________________________
    # save figure based on do_save contains either None or pathname
    do_savefigure(do_save, fig, dpi=save_dpi)
    plt.show(block=False)
    
    #___________________________________________________________________________
    return(fig, ax, cbar)



#+___PLOT MERIDIONAL OVERTRUNING CIRCULATION TIME-SERIES_______________________+
#|                                                                             |
#+_____________________________________________________________________________+
def plot_zmoc_tseries(moct_list, input_names, which_cycl=None, which_lat=['max'], 
                       which_moc='amoc', do_allcycl=False, do_concat=False, ymaxstep=1, xmaxstep=5,
                       str_descript='', str_time='', figsize=[], do_rapid=None, 
                       do_save=None, save_dpi=600, do_pltmean=True, do_pltstd=False ):    
    
    import matplotlib.patheffects as path_effects
    from matplotlib.ticker import AutoMinorLocator, MultipleLocator

    if len(figsize)==0: figsize=[13,6.5]
    if do_concat: figsize[0] = figsize[0]*2
    
    #___________________________________________________________________________
    # loop over which_lat list, either with single latitude entry 45.0 or 
    # string 'max'
    for lat in which_lat: 
        
        #_______________________________________________________________________
        # loop over vars dmoc_nadw or dmoc_aabw
        for var in list(moct_list[0].keys()):
            fig,ax= plt.figure(figsize=figsize),plt.gca()
        
            #___________________________________________________________________
            # setup colormap
            if do_allcycl: 
                if which_cycl is not None:
                    cmap = categorical_cmap(np.int32(len(moct_list)/which_cycl), which_cycl, cmap="tab10")
                else: cmap = categorical_cmap(len(moct_list), 1, cmap="tab10")
            else: cmap = categorical_cmap(len(moct_list), 1, cmap="tab10")
            
            #___________________________________________________________________
            ii, ii_cycle = 0, 1
            if which_cycl is None: aux_which_cycl = 1
            else                 : aux_which_cycl = which_cycl
            
            #___________________________________________________________________
            # loop over time series in moct_list
            for ii_ts, (tseries, tname) in enumerate(zip(moct_list, input_names)):
                data = tseries[var]
                #_______________________________________________________________
                # select moc values from single latitude or latidude range
                if lat=='max':
                    if var=='zmoc_aabw': data = data.isel(lat=(data.lat>40) & (data.lat<60)).min(dim='lat') 
                    if var=='zmoc_nadw': data = data.isel(lat=(data.lat>40) & (data.lat<60)).max(dim='lat') 
                    str_label= f'{40}°N<lat<{60}°N'
                elif isinstance(lat, list):    
                    if var=='zmoc_aabw': data = data.isel(lat=(data.lat>lat[0]) & (data.lat<lat[1])).min(dim='lat') 
                    if var=='zmoc_nadw': data = data.isel(lat=(data.lat>lat[0]) & (data.lat<lat[1])).max(dim='lat') 
                    str_label= f'{lat[0]}°N<lat<{lat[1]}°N'
                else:     
                    #data = data.sel(lat=lat)
                    data = data.isel(lat=np.argmin(np.abs(data['lat'].data-lat)))
                    if lat>=0: str_label= f'{lat}°N'
                    else     : str_label= f'{lat}°S'   
                data = data.groupby("time.year").mean()
                time = auxtime = data.year
                tlim, tdel = [time[0], time[-1]], time[-1]-time[0]
                if do_concat: auxtime = auxtime + (tdel+1)*(ii_cycle-1)
                #_______________________________________________________________
                hp=ax.plot(auxtime, data, linewidth=1.5, label=tname, color=cmap.colors[ii_ts,:], marker='o', markerfacecolor='w', markersize=5, zorder=2)
                if np.mod(ii_ts+1,aux_which_cycl)==0 or do_allcycl==False:
                    dict_plt = {'markeredgecolor':'k', 'markeredgewidth':0.5, 'color':hp[0].get_color(), 'clip_box':False, 'clip_on':False, 'zorder':3}
                    if do_pltmean: 
                        plt.plot(time[0]-(tdel)*0.0120, data.mean(), marker='<', **dict_plt)
                    if do_pltstd:
                        plt.plot(time[0]-(tdel)*0.015, data.mean()+data.std(), marker='^', markersize=6, **dict_plt)
                        plt.plot(time[0]-(tdel)*0.015, data.mean()-data.std(), marker='v', markersize=6, **dict_plt)
                #_______________________________________________________________
                ii_cycle=ii_cycle+1
                if ii_cycle>aux_which_cycl: ii_cycle=1
                
            #___________________________________________________________________
            # add Rapid moc data @26.5°
            if do_rapid is not None and var == 'dmoc_nadw': 
                path = do_rapid
                rapid26 = xr.open_dataset(path)['moc_mar_hc10']
                rapid26_ym = rapid26.groupby('time.year').mean('time', skipna=True)
                time_rapid = rapid26_ym.year
                if do_allcycl: 
                    time_rapid = time_rapid + (aux_which_cycl-1)*(time[-1]-time[0]+1)
                    
                hpr=plt.plot(time_rapid,rapid26_ym.data,
                        linewidth=2, label='Rapid @ 26.5°N', color='k', marker='o', markerfacecolor='w', 
                        markersize=5, zorder=2)
                
                dict_plt = {'markeredgecolor':'k', 'markeredgewidth':0.5, 'color':'k', 'clip_box':False, 'clip_on':False, 'zorder':3}
                if do_pltmean: 
                    plt.plot(time[0]-(tdel)*0.0120, rapid26_ym.data.mean(), marker='<', markersize=8, **dict_plt)
                if do_pltstd:
                    plt.plot(time[0]-(tdel)*0.015, rapid26_ym.data.mean()+rapid26_ym.data.std(), marker='^', markersize=6, **dict_plt)                        
                    plt.plot(time[0]-(tdel)*0.015, rapid26_ym.data.mean()-rapid26_ym.data.std(), marker='v', markersize=6, **dict_plt)    
                del(rapid26)
            
            #___________________________________________________________________
            ax.legend(shadow=True, fancybox=True, frameon=True, #mode='None', 
                    bbox_to_anchor=(1.04,0.5), loc="center left", borderaxespad=0)
                    #bbox_to_anchor=(1.04, 1.0), ncol=1) #loc='lower right', 
            ax.set_xlabel('Time [years]',fontsize=12)
            ax.set_ylabel('{:s} in [Sv]'.format(which_moc.upper()),fontsize=12)
            
            if   var=='zmoc_nadw': str_cell, str_cells = 'upper cell strength', 'nadw'
            elif var=='zmoc_aabw': str_cell, str_cells = 'lower cell strength', 'aabw'
            ax.set_title(f'{str_cell} @ {str_label}', fontsize=12, fontweight='bold')
            
            #___________________________________________________________________
            xmajor_locator = MultipleLocator(base=xmaxstep) # this locator puts ticks at regular intervals
            ymajor_locator = MultipleLocator(base=ymaxstep) # this locator puts ticks at regular intervals
            ax.xaxis.set_major_locator(xmajor_locator)
            ax.yaxis.set_major_locator(ymajor_locator)
            
            xminor_locator = AutoMinorLocator(5)
            yminor_locator = AutoMinorLocator(4)
            ax.yaxis.set_minor_locator(yminor_locator)
            ax.xaxis.set_minor_locator(xminor_locator)
            
            plt.grid(which='major')
            if not do_concat:
                plt.xlim(time[0]-(time[-1]-time[0])*0.015,time[-1]+(time[-1]-time[0])*0.015)    
            else:    
                plt.xlim(time[0]-(time[-1]-time[0])*0.015,time[-1]+(time[-1]-time[0]+1)*(aux_which_cycl-1)+(time[-1]-time[0])*0.015)    
                
            #___________________________________________________________________
            plt.show()
            fig.canvas.draw()
            
            #___________________________________________________________________
            # save figure based on do_save contains either None or pathname
            aux_do_save = do_save
            if do_save is not None:
                aux_do_save = '{:s}_{:s}_{:s}{:s}'.format(do_save[:-4], str_cells, str_label.replace('°','').replace(' ','_'), do_save[-4:])
            do_savefigure(aux_do_save, fig, dpi=save_dpi)
    
    #___________________________________________________________________________
    return(fig,ax)
