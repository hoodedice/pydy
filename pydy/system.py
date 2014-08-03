
from .codegen.code import generate_ode_function
from scipy.integrate import odeint
from sympy import symbols

class System(object):
    """Manages the simulation (integration) of a system whose equations are
    given by KanesMethod.

    Many of the attributes are also properties, and can be directly modified.

    The usage of this class is to:

        1. specify your options either via the constructor or via the
           attributes.
        2. optionally, call `generate_ode_function` if you want to customize
           how this function is generated.
        3. call `integrate` to simulate your system.

    Examples
    --------
    The simplest usage of this class is as follows::

        km = KanesMethod(...)
        km.kanes_equations(force_list, body_list)
        sys = System(km)
        times = np.linspace(0, 5, 100)
        sys.integrate(times)

    In this case, we use defaults for the numerical values of the constants,
    specified quantities, initial conditions, etc. You probably won't like
    these defaults. You can also specify such values via constructor keyword
    arguments or via the attributes::

        sys = System(km, initial_conditions={symbol('q1'): 0.5})
        sys.constants = {symbol('m'): 5.0}
        sys.integrate(times)

    To double-check the constants, specifieds and states in your problem, look
    at::

        sys.constants_symbols()
        sys.specifieds_symbols()
        sys.states()

    In this case, the System generates the numerical ode function for you
    behind the scenes. If you want to customize how this function is generated,
    you must call `generate_ode_function` on your own::

        sys = System(KM)
        sys.generate_ode_function(generator='cython')
        sys.integrate(times)

    """
    def __init__(self, eom_method, constants=dict(), specifieds=dict(),
            ode_solver=odeint, initial_conditions=dict()):
        """See the class's attributes for a description of the arguments to
        this constructor.

        The parameters to this constructor are all attributes of the System.
        Actually, they are properties. With the exception of `eom_method`,
        these attributes can be modified directly at any future point.

        Parameters
        ----------
        eom_method : sympy.physics.mechanics.KanesMethod
            You must have called `KanesMethod.kanes_equations()` *before*
            constructing this `System`.
        constants : dict, optional (default: all 1.0)
        specifieds : dict, optional (default: all 0)
        ode_solver : function, optional (default: scipy.integrate.odeint)
        initial_conditions : dict, optional (default: all zero)

        """
        self._eom_method = eom_method

        # TODO what if user adds symbols after constructing a System?
        self._constants_symbols = self._Kane_constant_symbols()
        self._specifieds_symbols = self._Kane_undefined_dynamicsymbols()

        self.constants = constants
        self.specifieds = specifieds
        self.ode_solver = ode_solver
        self.initial_conditions = initial_conditions
        self._evaluate_ode_function = None

    @property
    def coordinates(self):
        return self.eom_method._q

    @property
    def speeds(self):
        return self.eom_method._u

    @property
    def states(self):
        """These are in the same order as used in integration (as passed into
        evaluate_ode_function).

        """
        return self.coordinates + self.speeds

    @property
    def eom_method(self):
        """ This is a sympy.physics.mechanics.KanesMethod. The method used to
        generate the equations of motion. Read-only.

        """
        return self._eom_method

    @property
    def constants(self):
        """A dict that provides the numerical values for the constants in the
        problem (all non-dynamics symbols). Keys are the symbols for the
        constants, and values are floats. Constants that are not specified in
        this dict are given a default value of 1.0.

        """
        return self._constants

    @constants.setter
    def constants(self, constants):
        print "DEBUG constants setter", constants
        self._check_constants(constants)
        self._constants = constants

    @property
    def constants_symbols(self):
        """The constants (not functions of time) in the system."""
        return self._constants_symbols

    def _check_constants(self, constants):
        print "DEBUG0 check constants", constants
        symbols = self.constants_symbols
        for k in constants.keys():
            if k not in symbols:
                raise ValueError("Symbol {} is not a constant.".format(k))

    def _constants_padded_with_defaults(self):
        return dict(self.constants.items() + {s: 1.0 for s in
            self.constants_symbols if s not in self.constants}.items())

    @property
    def specifieds(self):
        """A dict that provides numerical values for the specified quantities
        in the problem (all dynamicsymbols that are not given by the `method`).
        Keys are the symbols for the specified quantities, or a tuple of
        symbols, and values are the floats, arrays of floats, or functions that
        generate the values. If a dictionary value is a function, it must have
        the same signature as `f(x, t)`, the ode right-hand-side function (see
        the documentation for the `ode_solver` attribute). You needn't provide
        values for all specified symbols. Those for which you do not give a
        value will default to 0.0.

        Examples
        --------
        Keys can be individual symbols, or a tuple of symbols. Length of a
        value must match the length of the corresponding key. Values can be
        functions that return iterables::

            sys = System(km)
            sys.specifieds = {(a, b, c): np.ones(3), d: lambda x, t: -3 * x[0]}
            sys.specifieds = {(a, b, c): lambda x, t: np.ones(3)}

        """
        return self._specifieds

    @specifieds.setter
    def specifieds(self, specifieds):
        self._check_specifieds(specifieds)
        self._specifieds = specifieds

    @property
    def specifieds_symbols(self):
        """The dynamicsymbols you must specify."""
        # TODO eventually use a method in the KanesMethod class.
        return self._specifieds_symbols
        
    def _assert_is_specified_symbol(self, symbol, all_symbols):
        if symbol not in all_symbols:
            raise ValueError("Symbol {} is not a 'specified' symbol.".format(
                symbol))

    def _assert_symbol_appears_multiple_times(self, symbol, symbols_so_far):
        if symbol in symbols_so_far:
            raise ValueError("Symbol {} appears more than once.".format(
                symbol))

    def _check_specifieds(self, specifieds):
        symbols = self.specifieds_symbols

        symbols_so_far = list()

        for k, v in specifieds.items():

            # The symbols must be specifieds.
            if isinstance(k, tuple):
                for ki in k:
                    self._assert_is_specified_symbol(ki, symbols)
            else:
                self._assert_is_specified_symbol(k, symbols)

            # Each specified symbol can appear only once.
            if isinstance(k, tuple):
                for ki in k:
                    self._assert_symbol_appears_multiple_times(ki,
                            symbols_so_far)
                    symbols_so_far.append(ki)
            else:
                self._assert_symbol_appears_multiple_times(k, symbols_so_far)
                symbols_so_far.append(k)

    def _symbol_is_in_specifieds_dict(self, symbol, specifieds_dict):
        for k in specifieds_dict.keys():
            if symbol == k or (isinstance(k, tuple) and symbol in k):
                return True
        return False

    def _specifieds_padded_with_defaults(self):
        return dict(self.specifieds.items() + {s: 0.0 for s in
            self.specifieds_symbols if not
            self._symbol_is_in_specifieds_dict(s, self.specifieds)}.items())

    @property
    def ode_solver(self):
        """A function that performs forward integration. It must have the same
        signature as odeint, which is::
       
            x_history = ode_solver(f, x0, t, args=(args,))

        where f is a function f(x, t), x0 are the initial conditions, x_history
        is the history, x is the state, t is the time, and args is a keyword
        argument takes arguments that are then passed to f. The default is
        odeint.

        """
        return self._ode_solver

    @ode_solver.setter
    def ode_solver(self, ode_solver):
        if not hasattr(ode_solver, '__call__'):
            raise ValueError(
                    "`ode_solver` ({}) is not a function.".format(ode_solver))
        self._ode_solver = ode_solver

    @property
    def initial_conditions(self):
        """ Initial conditions for all states (coordinates and speeds). Keys
        are the symbols for the coordinates and speeds, and values are floats.
        Coordinates or speeds that are not specified in this dict are given a
        default value of 0.0.

        """
        return self._initial_conditions

    @initial_conditions.setter
    def initial_conditions(self, initial_conditions):
        self._check_initial_conditions(initial_conditions)
        self._initial_conditions = initial_conditions

    def _check_initial_conditions(self, initial_conditions):
        symbols = self.states
        print "DEBUG6 check initial conditions", initial_conditions
        for k in initial_conditions.keys():
            if k not in symbols:
                raise ValueError("Symbol {} is not a state.".format(k))

    def _initial_conditions_padded_with_defaults(self):
        return dict(self.initial_conditions.items() + {s: 0.0 for s in
            self.states if s not in self.initial_conditions}.items())

    @property
    def evaluate_ode_function(self):
        """A function generated by `generate_ode_function` that computes the
        state derivatives:
        
            x' = evaluate_ode_function(x, t, args=(...))

        This function is used by the `ode_solver`.

        """
        return self._evaluate_ode_function

    def generate_ode_function(self, generator='lambdify', **kwargs):
        """Calls `pydy.codegen.code.generate_ode_function` with the appropriate
        arguments, and sets the `evaluate_ode_function` attribute to the
        resulting function.

        Parameters
        ----------
        generator : str, optional (default: 'lambdify')
            See documentation for `pydy.codegen.code.generate_ode_function`
        kwargs
            All other kwargs are passed onto
            `pydy.codegen.code.generate_ode_function`. Don't specify the
            `specified` kwarg though; this class takes care of those.

        Returns
        -------
        evaluate_ode_function : function
            A function which evaluates the derivaties of the states.
        
        """
        self._evaluate_ode_function = generate_ode_function(
                # args:
                self.eom_method.mass_matrix_full,
                self.eom_method.forcing_full,
                self.constants_symbols,
                self.coordinates, self.speeds,
                # kwargs:
                specified=self.specifieds_symbols,
                generator=generator,
                **kwargs
                )
        return self.evaluate_ode_function

    def integrate(self, times):
        """Integrates the equations `evaluate_ode_function` using `ode_solver`.

        It is necessary to have first generated an ode function. If you have
        not done so, we do so automatically by invoking
        `generate_ode_function`. However, if you want to customize how this
        function is generated (e.g., change the generator to cython), you can
        call `generate_ode_function` on your own (before calling `integrate`).

        Returns
        -------
        x_history : np.array, shape(num_integrator_time_steps, 2)
            The trajectory of states (coordinates and speeds) through the
            requested time interval. num_integrator_time_steps is either
            len(times) if len(times) > 2, or is determined by the `ode_solver`.

        """
        # Users might have changed these properties by directly accessing the
        # dict, without using the setter. Before we integrate, make sure they
        # did not muck up these dicts.
        self._check_constants(self.constants)
        self._check_specifieds(self.specifieds)
        self._check_initial_conditions(self.initial_conditions)

        if self.evaluate_ode_function == None:
            self.generate_ode_function()

        init_conds_dict = self._initial_conditions_padded_with_defaults()
        initial_conditions_in_proper_order = \
                [init_conds_dict[k] for k in self.states]

        return self.ode_solver(
                self.evaluate_ode_function,
                initial_conditions_in_proper_order,
                times,
                args=({
                    'constants': self._constants_padded_with_defaults(),
                    'specified': self._specifieds_padded_with_defaults(),
                    },)
                )

    def _Kane_inlist_insyms(self):
        """TODO temporary."""
        uaux = self.eom_method._uaux
        uauxdot = [diff(i, t) for i in uaux]
        # dictionary of auxiliary speeds & derivatives which are equal to zero
        subdict = dict(
                list(zip(uaux + uauxdot, [0] * (len(uaux) + len(uauxdot)))))

        # Checking for dynamic symbols outside the dynamic differential
        # equations; throws error if there is.
        insyms = set(self.eom_method._q + self.eom_method._qdot +
                self.eom_method._u + self.eom_method._udot + uaux + uauxdot)
        inlist = (self.eom_method.forcing_full[:] +
                self.eom_method.mass_matrix_full[:])
        return inlist, insyms

    def _Kane_undefined_dynamicsymbols(self):
        """Similar to `_find_dynamicsymbols()`, except that it checks all syms
        used in the system. Code is copied from `linearize()`.

        TODO temporarily here until KanesMethod and Lagranges method have an
        interface for obtaining these quantities.

        """
        return list(self.eom_method._find_dynamicsymbols(
            *self._Kane_inlist_insyms()))

    def _Kane_constant_symbols(self):
        """Similar to `_find_othersymbols()`, except it checks all syms used in
        the system.

        Remove the time symbol.

        TODO temporary.

        """
        constants = list(self.eom_method._find_othersymbols(
            *self._Kane_inlist_insyms()))
        constants.remove(symbols('t'))
        return constants

   
