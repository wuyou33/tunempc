#
#    This file is part of TuneMPC.
#
#    TuneMPC -- A Tool for Economic Tuning of Tracking (N)MPC Problems.
#    Copyright (C) 2020 Jochem De Schutter, Mario Zanon, Moritz Diehl (ALU Freiburg).
#
#    TuneMPC is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 3 of the License, or (at your option) any later version.
#
#    TuneMPC is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with awebox; if not, write to the Free Software Foundation,
#    Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
#
#!/usr/bin/python3
"""Implementation of the periodic unicycle example as proposed in 

M. Zanon et al.
A Periodic Tracking MPC that is Locally Equivalent to Periodic Economic NMPC (section 7)
IFAC 2017 World Congress

:author: Jochem De Schutter

"""

import tunempc
import tunempc.pmpc as pmpc
import numpy as np
import casadi as ca
import casadi.tools as ct
import matplotlib.pyplot as plt

def problemData():

    """ Problem data, numeric constants,...
    """

    data = {}
    data['rho'] = 0.001
    data['v']   = 1

    return data

def dynamics(x, u, data, h = 1.0):

    """ System dynamics formulation (discrete time)
    """
    # state derivative
    xdot = ca.vertcat(
        data['v']*x['ez'],
        data['v']*x['ey'],
        - u['u']*x['ey'] - data['rho']*x['ez']*(x['ez']**2 + x['ey']**2 - 1.0),
        u['u']*x['ez'] - data['rho']*x['ey']*(x['ez']**2 + x['ey']**2 - 1.0) 
        )

    # set-up ode system
    f  = ca.Function('f',[x,u],[xdot])
    ode = {'x':x, 'p':u,'ode': f(x,u)}

    return ca.integrator('F','rk',ode,{'tf':h,'number_of_finite_elements':50})

def vars():

    """ System states and controls
    """

    x = ct.struct_symMX(['z','y','ez','ey'])
    u = ct.struct_symMX(['u'])

    return x, u

def objective(x, u, data):

    # cost definition
    obj = u['u']**2 + x['z']**2 + 5*x['y']**2

    return  ca.Function('cost',[x,u],[obj])

# discretization
T = 5 # [s]
N = 30

# set-up system
x, u = vars()
nx = x.shape[0]
nu = u.shape[0]
data = problemData()

tuner = tunempc.Tuner(
    f = dynamics(x, u, data, h= T/N),
    l =  objective(x,u,data),
    p = N
)

# initialization
t = np.linspace(0,T,N+1)
ez0 = list(map(np.cos, 2*np.pi*t/T))
ey0 = list(map(np.sin, 2*np.pi*t/T))
inv = list(map(lambda x, y: x**2 + y**2 - 1.0, ez0, ey0))
z0  = list(map(lambda x : data['v']*T/(2*np.pi)*np.sin(x), 2*np.pi*t/T))
y0  = list(map(lambda x : - data['v']*T/(2*np.pi)*np.cos(x), 2*np.pi*t/T))

# create initial guess
w0 = tuner.pocp.w(0.0)
for i in range(N):
    w0['x',i] = ct.vertcat(z0[i], y0[i],ez0[i], ey0[i])
w0['u'] = 2*np.pi/T

wsol = tuner.solve_ocp(w0 = w0.cat)
Hc   = tuner.convexify(solver='mosek')
[H, q, _, _, _]  = tuner.pocp.get_sensitivities()

# add projection operator for terminal constraint
sys = tuner.sys

# mpc options
opts = {}
opts['p_operator'] = ca.Function(
    'p_operator',
    [sys['vars']['x']],
    [sys['vars']['x'][0:3]]
    )

ctrls = {}

# economic mpc controller
opts['ipopt_presolve'] = True
ctrlE = tuner.create_mpc('economic', N, opts=opts)

# normal tracking mpc controller
tuningTn = {'H': [np.diag([1.0, 1.0, 1.0, 1.0, 1.0])]*N, 'q': q}
ctrlTn = tuner.create_mpc('tracking', N, opts=opts, tuning = tuningTn)

# tuned tracking mpc controller
ctrlTt = tuner.create_mpc('tuned', N, opts=opts)

# disturbance
dist_z  = [0.1, 0.1, 0.5, 0.5]
Nstep   = [0, 34, 69, 105]

# initialize
uE, uTn, uTt = [], [], []
lE, lTn, lTt = [], [], []

x_initE  = wsol['x',0]
x_initTn = wsol['x',0]
x_initTt = wsol['x',0]
plant_sim = dynamics(x, u, data, h= T/N)

Nsim  = 250
tgrid = [T/N*i for i in range(Nsim)]
for k in range(Nsim):

    if k in Nstep:
        dist = dist_z[Nstep.index(k)]
        x_initE[0]  += dist
        x_initTn[0] += dist
        x_initTt[0] += dist

    uE.append(ctrlE.step(x_initE))
    uTn.append(ctrlTn.step(x_initTn))
    uTt.append(ctrlTt.step(x_initTt))

    lOpt = tuner.l(wsol['x', k%N], wsol['u',k%N])
    lE.append(tuner.l(x_initE,uE[-1]) - lOpt)
    lTn.append(tuner.l(x_initTn,uTn[-1]) - lOpt)
    lTt.append(tuner.l(x_initTt,uTt[-1]) - lOpt)

    # forward sim
    x_initE  = plant_sim(x0 = x_initE,  p = uE[-1])['xf']
    x_initTn = plant_sim(x0 = x_initTn, p = uTn[-1])['xf']
    x_initTt = plant_sim(x0 = x_initTt, p = uTt[-1])['xf']

# plot feedback controls to check equivalence
for i in range(nu):
    plt.figure(i)
    plt.step(tgrid,[uE[j][i] - wsol['u',j%N][i] for j in range(len(uE))])
    plt.step(tgrid,[uTn[j][i] - wsol['u',j%N][i] for j in range(len(uTn))])
    plt.step(tgrid,[uTt[j][i] - wsol['u',j%N][i] for j in range(len(uTt))])
    plt.legend(['economic', 'tracking', 'tuned'])
    plt.title('Feedback control deviation')

plt.figure(nu)
plt.step(tgrid,lE)
plt.step(tgrid,lTn)
plt.step(tgrid,lTt)
plt.legend(['economic', 'tracking', 'tuned'])
plt.title('Stage cost deviation')

plt.show()
