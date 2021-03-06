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
"""Evaporation process example as described in:

A tracking MPC formulation that is locally equivalent to economic MPC 
M. Zanon, S. Gros, M. Diehl 
Journal of Process Control 2016
(section 8) 

:author: Jochem De Schutter

"""

import tunempc
import tunempc.pmpc
import tunempc.closed_loop_tools as clt
import numpy as np
import casadi as ca
import casadi.tools as ct
import matplotlib.pyplot as plt

def problem_data():

    """ Problem data, numeric constants,...
    """

    data = {}
    data['a'] = 0.5616
    data['b'] = 0.3126
    data['c'] = 48.43
    data['d'] = 0.507
    data['e'] = 55.0
    data['f'] = 0.1538
    data['g'] = 90.0
    data['h'] = 0.16

    data['M'] = 20.0
    data['C'] = 4.0
    data['UA2'] = 6.84
    data['Cp'] = 0.07
    data['lam'] = 38.5
    data['lams'] = 36.6
    data['F1'] = 10.0
    data ['X1'] = 5.0
    data['F3'] = 50.0
    data['T1'] = 40.0
    data['T200'] = 25.0

    return data

def intermediate_vars(x, u, data):

    """ Intermediate model variables
    """

    data['T2'] = data['a']*x['P2'] + data['b']*x['X2'] + data['c']
    data['T3'] = data['d']*x['P2'] + data['e']
    data['T100'] = data['f']*u['P100'] + data['g']
    data['UA1'] = data['h']*(data['F1']+data['F3'])
    data['Q100'] = data['UA1']*(data['T100'] - data['T2'])
    data['F100'] = data['Q100']/data['lams']
    data['Q200'] = data['UA2']*(data['T3']-data['T200'])/(1.0 + data['UA2']/(2.0*data['Cp']*u['F200']))
    data['F5'] = data['Q200']/data['lam']
    data['F4'] = (data['Q100']-data['F1']*data['Cp']*(data['T2']-data['T1']))/data['lam']
    data['F2'] = data['F1'] - data['F4'] 

    return data

def dynamics(x, u, data):

    """ System dynamics function (discrete time)
    """

    # state derivative expression
    xdot = ca.vertcat(
        (data['F1']*data['X1'] - data['F2']*x['X2'])/data['M'],
        (data['F4'] - data['F5'])/data['C']
        )

    # create ode for integrator
    ode = {'x':x, 'p':u,'ode': xdot}

    return ca.integrator('F','collocation',ode,{'tf':1})

def vars():

    """ System states and controls
    """

    x = ct.struct_symMX(['X2','P2'])
    u = ct.struct_symMX(['P100','F200'])

    return x, u

def objective(x, u, data):

    """ Economic objective function
    """
    
    # cost definition
    obj = 10.09*(data['F2']+data['F3']) + 600.0*data['F100'] + 0.6*u['F200']

    return ca.Function('economic_cost',[x,u],[obj])

def constraints(x, u, data):
    
    """ Path inequality constraints function (convention h(x,u) >= 0)
    """

    constr = ca.vertcat(
        x['X2'] - 25.0,
        x['P2'] - 40.0,
        80.0 - x['P2'],
        400.0 - u['P100'],
        400.0 - u['F200'],
    )

    return ca.Function('h', [x,u], [constr])


# set-up system
x, u = vars()
data = intermediate_vars(x,u, problem_data())
nx = x.shape[0]
nu = u.shape[0]

tuner = tunempc.Tuner(
    f = dynamics(x, u, data),
    l = objective(x,u,data),
    h = constraints(x,u, data),
    p = 1
)

# solve
w0 = ca.vertcat(*[25.0, 49.743, 191.713, 215.888])
wsol = tuner.solve_ocp(w0)
Hc = tuner.convexify(rho = 1e-3, force = False, solver='mosek')

# nmpc horizon length
N = 200

# gradient
[H, q, _, _, _]  = tuner.pocp.get_sensitivities()

# economic mpc controller
ctrls = {}
sys  = tuner.sys
ctrls['economic'] = tuner.create_mpc('economic',N = N)

# normal tracking mpc controller
tuningTn = {'H': [np.diag([10.0, 10.0, 0.1, 0.1])], 'q': q}
ctrls['tracking'] = tuner.create_mpc('tracking',N = N, tuning = tuningTn)

# tuned tracking mpc controller
ctrls['tuned'] = tuner.create_mpc('tuned',N = N)

alpha = [0.1, 0.5, 1.0]
log = clt.check_equivalence(ctrls, objective(x,u,data), sys['h'], wsol['x',0], ca.vertcat(0.0, 10.0), alpha)

# plot feedback controls to check equivalence
for name in list(ctrls.keys()):
    for i in range(nu):
        plt.figure(i)
        plt.plot(alpha, [log[j]['u'][name][0][i] for j in range(len(alpha))])
        plt.legend(list(ctrls.keys()))

plt.show()
